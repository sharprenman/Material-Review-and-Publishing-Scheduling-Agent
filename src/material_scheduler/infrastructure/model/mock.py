"""Explicit offline fixture. Decisions here never count as live model evidence."""

import json
from uuid import uuid4


class MockModel:
    mode = "mock"
    name = "offline-test-double"

    def choose(self, messages: list[dict], tools: list[dict], timeout: float) -> dict:
        results = {}
        proposal = None
        for message in messages:
            if message["role"] == "user" and message.get("content", "").startswith(
                '{"context_packet":'
            ):
                packet = json.loads(message["content"])["context_packet"]
                results.update(packet["working_memory"]["current_observations"])
                proposal = packet["working_memory"]["current_proposal"]
            if message["role"] == "user" and message.get("content", "").startswith('{"request":'):
                proposal = json.loads(message["content"]).get("accepted_proposal")
            if message["role"] == "tool":
                results[message["name"]] = json.loads(message["content"])
        name, arguments = "read_material", {}
        if "read_material" in results:
            name = "check_rules"
        review = results.get("check_rules", {})
        if review:
            if review.get("status") in {"missing", "blocked"}:
                name, arguments = "finish", {"reason": review["status"]}
            else:
                name = "query_slots"
                options = results.get("query_slots", {}).get("slots", [])
                if options:
                    available = [s["time"] for s in options if s["available"]]
                    if available:
                        chosen = (
                            proposal["time"]
                            if proposal
                            and proposal["confirmation"] == "accepted"
                            and proposal["time"] in available
                            else available[0]
                        )
                        name, arguments = "save_draft", {"time": chosen}
                    else:
                        name, arguments = "finish", {"reason": "no_slots"}
        rationale = {
            "read_material": "需要读取当前请求素材，尚无素材观察。",
            "check_rules": "素材读取完成，需要检查缺失项和规则风险。",
            "query_slots": "审核通过，需要查询当前占用与可用候选。",
            "save_draft": "查询返回了可用候选，选择其中最早时段提交。",
            "finish": "审核缺失、风险或无时段，不具备继续保存条件。",
        }[name]
        return {"id": str(uuid4()), "name": name, "arguments": arguments, "rationale": rationale}
