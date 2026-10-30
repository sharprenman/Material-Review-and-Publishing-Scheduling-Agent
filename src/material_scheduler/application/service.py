import json
import sqlite3
from contextlib import contextmanager

from langgraph.errors import GraphRecursionError
from langgraph.types import Command

from material_scheduler.application.agent.graph import PROMPT, build_graph
from material_scheduler.application.ports import Model
from material_scheduler.application.tools import Tools
from material_scheduler.domain.errors import BusinessError
from material_scheduler.domain.models import Confirmation, RunResult, ScheduleRequest


class Service:
    def __init__(
        self,
        repository,
        catalog,
        model: Model,
        settings,
        checkpoint_db,
        checkpointer,
        trace_factory,
        memory,
        context,
    ):
        self.repo, self.catalog, self.model, self.settings = repository, catalog, model, settings
        self.checkpoint_db = checkpoint_db
        self.checkpointer = checkpointer
        self.trace_factory = trace_factory
        self.memory, self.context = memory, context

    @contextmanager
    def lock(self):
        # One local CLI writer at a time, including across processes. SQLite protects reservations.
        import fcntl

        with (self.settings.runtime_dir / "execution.lock").open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def graph(self, request_id):
        row = self.repo.get(request_id)
        if row["mode"] != self.model.mode:
            raise BusinessError("恢复必须使用原始运行模式")
        trace = self.trace_factory(
            self.settings.runtime_dir / "traces" / f"{row['run_id']}.jsonl",
            {k: row[k] for k in ("run_id", "thread_id", "mode")}
            | {"request_id": request_id, "model": self.model.name},
        )
        return build_graph(
            self.repo,
            self.model,
            Tools(self.repo, self.catalog),
            self.settings,
            request_id,
            trace,
            self.checkpointer,
            self.context,
        )

    def config(self, request_id):
        return {
            "configurable": {"thread_id": self.repo.get(request_id)["thread_id"]},
            "recursion_limit": 128,
        }

    def invoke(self, request_id, payload):
        try:
            self.graph(request_id).invoke(payload, config=self.config(request_id))
        except GraphRecursionError:
            self.repo.update(request_id, execution="incomplete", error="框架步骤上限")
        row = self.repo.get(request_id)
        snapshot = self.graph(request_id).get_state(self.config(request_id)).values
        version = snapshot.get("observation_meta", {}).get("check_rules", {}).get("rules_version")
        try:
            if version:
                self.memory.remember(row, version, self.settings.memory_ttl_days)
        except (OSError, sqlite3.Error):
            self.trace_factory(
                self.settings.runtime_dir / "traces" / f"{row['run_id']}.jsonl",
                {"request_id": request_id, "run_id": row["run_id"], "mode": row["mode"]},
            ).emit(event="memory_write_failed", next_action="end")
        return self.status(request_id)

    def run(self, request: ScheduleRequest):
        with self.lock():
            created = self.repo.register(request, self.model.mode)
            row = self.repo.get(request.request_id)
            if not created:
                snapshot = self.graph(request.request_id).get_state(self.config(request.request_id))
                if snapshot.next and not snapshot.interrupts:
                    return self.invoke(request.request_id, None)
                if row["execution"] == "waiting_confirmation":
                    p = row["proposal"]
                    if p and p["confirmation"] != "pending":
                        return self.invoke(request.request_id, Command(resume=True))
                if row["execution"] != "running":
                    return self.status(request.request_id)
                graph = self.graph(request.request_id)
                if graph.get_state(self.config(request.request_id)).values:
                    return self.invoke(request.request_id, None)
            state = {
                "messages": [
                    {"role": "system", "content": PROMPT},
                    {"role": "user", "content": request.model_dump_json()},
                ],
                "observations": {},
                "action": {},
                "route": "decide",
            }
            return self.invoke(request.request_id, state)

    def confirm(self, request_id: str, confirmation: Confirmation):
        with self.lock():
            graph = self.graph(request_id)
            snapshot = graph.get_state(self.config(request_id))
            if snapshot.next and not snapshot.interrupts:
                self.invoke(request_id, None)
            self.repo.confirm(request_id, confirmation)
            return self.invoke(request_id, Command(resume=True))

    def status(self, request_id: str) -> RunResult:
        row = self.repo.get(request_id)
        draft = self.repo.draft(request_id)
        return RunResult(
            request_id=request_id,
            run_id=row["run_id"],
            thread_id=row["thread_id"],
            mode=row["mode"],
            execution="completed" if draft else row["execution"],
            requested_time=row["body"]["requested_time"],
            review=row["review"],
            proposal=row["proposal"],
            save_status="saved"
            if draft
            else "failed"
            if row["execution"] == "failed"
            else "not_saved",
            draft=draft,
            error=row["error"],
            model_calls=row["model_calls"],
            tool_calls=row["tool_calls"],
        )

    def trace(self, request_id: str) -> dict:
        row = self.repo.get(request_id)
        path = self.settings.runtime_dir / "traces" / f"{row['run_id']}.jsonl"
        events = (
            [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
            if path.exists()
            else []
        )
        return {"request_id": request_id, "mode": row["mode"], "events": events}

    def close(self):
        self.memory.close()
        self.checkpoint_db.close()
        self.repo.close()
