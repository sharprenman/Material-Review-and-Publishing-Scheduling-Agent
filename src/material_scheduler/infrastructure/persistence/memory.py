"""Advisory cases, isolated by account, mode and rule version. No user preferences."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


class CaseMemory:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS cases (
              source_run_id TEXT PRIMARY KEY, source_request_id TEXT NOT NULL,
              channel TEXT NOT NULL, account TEXT NOT NULL, mode TEXT NOT NULL,
              material_id TEXT NOT NULL, problem TEXT NOT NULL, rules_version TEXT NOT NULL,
              outcome TEXT NOT NULL, facts TEXT NOT NULL, source_trace TEXT NOT NULL,
              created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
              disabled INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS case_scope ON cases(channel,account,mode,rules_version);
            PRAGMA user_version=1;
            """)
        except sqlite3.Error:
            self.db.close()
            raise

    def remember(self, row: dict, rules_version: str, ttl_days: int):
        if row["execution"] not in {"completed", "blocked", "rejected"}:
            return
        request, audit, proposal = row["body"], row["review"] or {}, row["proposal"]
        problem = (
            audit.get("status")
            if audit.get("status") in {"blocked", "missing"}
            else "conflict"
            if proposal
            else "normal"
        )
        # These facts come from business state, never model rationale. Authorization is not copied.
        facts = {
            "requested_time": request["requested_time"],
            "review_status": audit.get("status"),
            "missing": audit.get("missing", []),
            "risks": audit.get("risks", []),
            "suggested_time": proposal["time"] if proposal else None,
        }
        now = datetime.now(UTC)
        with self.db:
            self.db.execute(
                """INSERT OR IGNORE INTO cases
              (source_run_id,source_request_id,channel,account,mode,material_id,problem,
               rules_version,outcome,facts,source_trace,created_at,expires_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    row["run_id"],
                    row["id"],
                    request["channel"],
                    request["account"],
                    row["mode"],
                    request["material_id"],
                    problem,
                    rules_version,
                    row["execution"],
                    json.dumps(facts, ensure_ascii=False),
                    f"traces/{row['run_id']}.jsonl",
                    now.isoformat(),
                    (now + timedelta(days=ttl_days)).isoformat(),
                ),
            )

    def search(
        self, request: dict, mode: str, rules_version: str, problem: str, limit: int
    ) -> list[dict]:
        if limit == 0:
            return []
        rows = self.db.execute(
            """SELECT *,
          (CASE WHEN problem=? THEN 4 ELSE 0 END +
           CASE WHEN material_id=? THEN 2 ELSE 0 END) AS score
          FROM cases WHERE channel=? AND account=? AND mode=? AND rules_version=?
          AND disabled=0 AND expires_at>? AND source_request_id<>?
          AND (problem=? OR material_id=?)
          ORDER BY score DESC, created_at DESC, source_run_id LIMIT ?""",
            (
                problem,
                request["material_id"],
                request["channel"],
                request["account"],
                mode,
                rules_version,
                datetime.now(UTC).isoformat(),
                request["request_id"],
                problem,
                request["material_id"],
                limit,
            ),
        )
        result = []
        for row in rows:
            result.append(
                {
                    "source_run_id": row["source_run_id"],
                    "source_request_id": row["source_request_id"],
                    "source_trace": row["source_trace"],
                    "rules_version": row["rules_version"],
                    "created_at": row["created_at"],
                    "expires_at": row["expires_at"],
                    "outcome": row["outcome"],
                    "facts": json.loads(row["facts"]),
                    "retrieval_reason": "同渠道、账号、模式与规则版本；"
                    + ("问题类型相同" if row["problem"] == problem else "素材相同"),
                    "score": row["score"],
                    "advisory_only": True,
                }
            )
        return result

    def disable(self, source_run_id: str):
        with self.db:
            self.db.execute("UPDATE cases SET disabled=1 WHERE source_run_id=?", (source_run_id,))

    def close(self):
        self.db.close()


class UnavailableCaseMemory:
    """Keep business execution available when the independent memory file cannot open."""

    def search(self, *args, **kwargs):
        raise OSError("历史案例存储不可用")

    def remember(self, *args, **kwargs):
        raise OSError("历史案例存储不可用")

    def close(self):
        pass
