"""Business facts, unique identities and reservations share one SQLite transaction."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from material_scheduler.domain.errors import BudgetExceeded, BusinessError
from material_scheduler.domain.models import Confirmation, Draft, ScheduleRequest


class Repository:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS requests (
          id TEXT PRIMARY KEY, digest TEXT NOT NULL, body TEXT NOT NULL,
          run_id TEXT NOT NULL, thread_id TEXT NOT NULL UNIQUE, mode TEXT NOT NULL,
          execution TEXT NOT NULL DEFAULT 'running', review TEXT, proposal TEXT,
          error TEXT, model_calls INTEGER NOT NULL DEFAULT 0,
          tool_calls INTEGER NOT NULL DEFAULT 0, active_seconds REAL NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS drafts (
          request_id TEXT PRIMARY KEY REFERENCES requests(id), body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS slots (
          channel TEXT NOT NULL, account TEXT NOT NULL, time TEXT NOT NULL,
          owner TEXT NOT NULL, PRIMARY KEY(channel, account, time));
        CREATE TABLE IF NOT EXISTS imports (name TEXT PRIMARY KEY);
        PRAGMA user_version=1;
        """)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def initialize(self, schedules: list[dict]):
        with self.transaction():
            if self.db.execute("SELECT 1 FROM imports WHERE name='schedules'").fetchone():
                return
            for row in schedules:
                self.db.execute(
                    "INSERT INTO slots VALUES(?,?,?,?)",
                    (row["channel"], row["account"], row["time"], "seed"),
                )
            self.db.execute("INSERT INTO imports VALUES('schedules')")

    def register(self, request: ScheduleRequest, mode: str):
        body = request.model_dump_json()
        digest = hashlib.sha256(body.encode()).hexdigest()
        with self.transaction():
            row = self.db.execute(
                "SELECT digest FROM requests WHERE id=?", (request.request_id,)
            ).fetchone()
            if row:
                if row["digest"] != digest:
                    raise BusinessError("request_id 已用于不同业务内容")
                return False
            self.db.execute(
                "INSERT INTO requests(id,digest,body,run_id,thread_id,mode) VALUES(?,?,?,?,?,?)",
                (request.request_id, digest, body, str(uuid4()), str(uuid4()), mode),
            )
        return True

    def get(self, request_id: str) -> dict:
        row = self.db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise BusinessError("请求不存在")
        result = dict(row)
        for key in ("body", "review", "proposal"):
            result[key] = json.loads(result[key]) if result[key] else None
        return result

    def update(self, request_id: str, **values):
        allowed = {"execution", "review", "proposal", "error"}
        if not values.keys() <= allowed:
            raise ValueError("unsupported update")
        normalized = {
            k: json.dumps(v, ensure_ascii=False)
            if k in {"review", "proposal"} and v is not None
            else v
            for k, v in values.items()
        }
        with self.db:
            self.db.execute(
                "UPDATE requests SET " + ",".join(f"{k}=?" for k in normalized) + " WHERE id=?",
                (*normalized.values(), request_id),
            )

    def consume(self, request_id: str, kind: str, limit: int, seconds: float):
        column = {"model": "model_calls", "tool": "tool_calls"}[kind]
        with self.transaction():
            row = self.get(request_id)
            if row[column] >= limit or row["active_seconds"] >= seconds:
                raise BudgetExceeded("累计执行预算耗尽，执行未完成")
            self.db.execute(f"UPDATE requests SET {column}={column}+1 WHERE id=?", (request_id,))

    def elapsed(self, request_id: str, seconds: float):
        with self.db:
            self.db.execute(
                "UPDATE requests SET active_seconds=active_seconds+? WHERE id=?",
                (seconds, request_id),
            )

    def slots(self, request: ScheduleRequest) -> list[dict]:
        start = request.requested_time
        options = []
        for hour in range(start.hour, 24):
            time = (start + timedelta(hours=hour - start.hour)).isoformat()
            row = self.db.execute(
                "SELECT owner FROM slots WHERE channel=? AND account=? AND time=?",
                (request.channel, request.account, time),
            ).fetchone()
            options.append({"time": time, "available": row is None})
        return options

    def draft(self, request_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT body FROM drafts WHERE request_id=?", (request_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def confirm(self, request_id: str, confirmation: Confirmation):
        with self.transaction():
            row = self.get(request_id)
            p = row["proposal"]
            if (
                not p
                or row["execution"] != "waiting_confirmation"
                or p["proposal_id"] != confirmation.proposal_id
                or p["version"] != confirmation.version
                or p["confirmation"] != "pending"
            ):
                raise BusinessError("方案不存在、版本过期或已处理")
            p["confirmation"] = "accepted" if confirmation.accept else "rejected"
            self.db.execute(
                "UPDATE requests SET proposal=? WHERE id=?", (json.dumps(p), request_id)
            )

    def save(self, request: ScheduleRequest, time: str, evaluate, observed_slots=None):
        with self.transaction():
            existing = self.draft(request.request_id)
            if existing:
                return {"saved": True, "draft": existing}
            fresh_review = evaluate().model_dump()
            self.db.execute(
                "UPDATE requests SET review=? WHERE id=?",
                (json.dumps(fresh_review), request.request_id),
            )
            if fresh_review["status"] != "passed":
                return {"saved": False, "review": fresh_review}
            latest_slots = self.slots(request)
            if observed_slots is not None and observed_slots != latest_slots:
                return {
                    "saved": False,
                    "conflict": True,
                    "error": "最新占用已变化，请重新 query_slots",
                }
            available = [s["time"] for s in latest_slots if s["available"]]
            if time not in available:
                return {"saved": False, "conflict": True, "message": "最新占用已变化，请重新查询"}
            row = self.get(request.request_id)
            p = row["proposal"]
            accepted = p and p["confirmation"] == "accepted" and p["time"] in available
            if accepted and time != p["time"]:
                return {"error": "当前有效确认绑定其他时间，请使用已确认时间"}
            if not accepted and time != available[0]:
                return {"error": "必须选择最早可用候选，请依据 query_slots 调整"}
            if time != request.requested_time.isoformat():
                p = row["proposal"]
                if not (p and p["time"] == time and p["confirmation"] == "accepted"):
                    if p and p["time"] == time and p["confirmation"] == "pending":
                        return {"saved": False, "proposal": p}
                    p = {
                        "proposal_id": str(uuid4()),
                        "version": (p["version"] + 1 if p else 1),
                        "time": time,
                        "confirmation": "pending",
                    }
                    self.db.execute(
                        "UPDATE requests SET proposal=?,execution=? WHERE id=?",
                        (json.dumps(p), "waiting_confirmation", request.request_id),
                    )
                    return {"saved": False, "proposal": p}
            draft = Draft(
                draft_id=str(uuid4()),
                request_id=request.request_id,
                material_id=request.material_id,
                channel=request.channel,
                account=request.account,
                time=time,
            ).model_dump()
            self.db.execute(
                "INSERT INTO slots VALUES(?,?,?,?)",
                (request.channel, request.account, time, request.request_id),
            )
            self.db.execute(
                "INSERT INTO drafts VALUES(?,?)", (request.request_id, json.dumps(draft))
            )
            self.db.execute(
                "UPDATE requests SET execution='completed',error=NULL WHERE id=?",
                (request.request_id,),
            )
            return {"saved": True, "draft": draft}

    def close(self):
        self.db.close()
