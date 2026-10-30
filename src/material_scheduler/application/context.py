"""Bounded, provenance-aware model context. Tool guards never consume advisory memory."""

import copy
import json
import sqlite3
from datetime import UTC, datetime

from material_scheduler.domain.errors import BusinessError


def estimate_size(messages: list[dict], tools: list[dict]) -> int:
    # Conservative UTF-8 byte proxy + framing reserve, NOT the model's exact token count.
    return (
        len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False).encode()) + 128
    )


def project_observation(name: str, result: dict) -> dict:
    if name == "read_material":
        material = result.get("material")
        return {
            "material": {
                "material_id": material["material_id"],
                "title_present": bool(material.get("title")),
                "title": (material.get("title") or "")[:160],
                "title_truncated": len(material.get("title") or "") > 160,
                "rights": material.get("rights"),
            }
            if material
            else None,
            "missing": result.get("missing", []),
        }
    return copy.deepcopy(result)


def exchanges(messages: list[dict]) -> list[list[dict]]:
    """Retain or remove whole assistant/tool pairs, never orphan a protocol message."""
    pairs = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message["role"] in {"system", "user"}:
            index += 1
            continue
        calls = message.get("tool_calls", [])
        if (
            message["role"] != "assistant"
            or len(calls) != 1
            or index + 1 >= len(messages)
            or messages[index + 1].get("role") != "tool"
            or messages[index + 1].get("tool_call_id") != calls[0]["id"]
        ):
            raise BusinessError("上下文工具调用与返回不完整，执行未完成")
        pairs.append([message, messages[index + 1]])
        index += 2
    return pairs


def summarize(previous: dict, pairs: list[list[dict]]) -> dict:
    summary = copy.deepcopy(previous) or {"covered_pairs": 0, "last_observation_by_tool": {}}
    for _assistant, tool in pairs:
        name = tool["name"]
        observation = project_observation(name, json.loads(tool["content"]))
        summary["last_observation_by_tool"][name] = {
            "observation": observation,
            "source_call_id": tool["tool_call_id"],
            "source": tool.get("_context_source", {"freshness": "legacy_unknown"}),
            "historical_only": True,
        }
        summary["covered_pairs"] += 1
    return summary


class ContextBuilder:
    def __init__(self, repo, catalog, memory, settings):
        self.repo, self.catalog, self.memory, self.settings = repo, catalog, memory, settings

    def valid_observations(self, state: dict, request_id: str) -> tuple[dict, list[str]]:
        """Full current evidence, independent of model projection and context strategy."""
        row = self.repo.get(request_id)
        rules_version = self.catalog.rules_version()
        material_version = self.catalog.material_version(row["body"]["material_id"])
        observations = state["observations"]
        meta = state.get("observation_meta", {})
        current = {}
        invalidated = []
        for name, result in observations.items():
            source = meta.get(name, {})
            valid = bool(source) and source.get("generation", 0) == state.get("generation", 0)
            if name in {"read_material", "check_rules"}:
                valid = (
                    valid
                    and source.get("material_version") == material_version
                    and source.get("rules_version") == rules_version
                )
            if name == "query_slots":
                conflict = observations.get("save_draft", {}).get("conflict")
                conflict_step = meta.get("save_draft", {}).get("source_step", -1)
                valid = valid and (not conflict or source.get("source_step", -1) > conflict_step)
                if valid:
                    age = (
                        datetime.now(UTC) - datetime.fromisoformat(source["observed_at"])
                    ).total_seconds()
                    valid = 0 <= age <= 60
            if valid:
                current[name] = result
            else:
                invalidated.append(name)
        return current, invalidated

    def prepare(self, state: dict, request_id: str, prompt: str, tools: list[dict]) -> dict:
        row = self.repo.get(request_id)
        original = state["messages"]
        clean_original = [
            {k: v for k, v in message.items() if not k.startswith("_")} for message in original
        ]
        before = estimate_size(clean_original, tools)
        audit = {
            "strategy": "optimized" if self.settings.context_enabled else "baseline",
            "size_method": "utf8_bytes_proxy_not_exact_tokens",
            "before_estimate": before,
            "budget": self.settings.context_max_estimate,
        }
        if not self.settings.context_enabled:
            if before > self.settings.context_max_estimate:
                raise BusinessError("上下文预算不足，原始消息超过限制；未调用模型")
            return {
                "messages": clean_original,
                "history": original,
                "working_memory": state.get("working_memory", {}),
                "summary": state.get("summary", {}),
                "audit": audit
                | {
                    "after_estimate": before,
                    "retained_pairs": len(exchanges(original)),
                    "dropped_pairs": 0,
                    "retrieved_cases": [],
                },
            }

        rules_version = self.catalog.rules_version()
        observations = state["observations"]
        meta = state.get("observation_meta", {})
        valid, invalidated = self.valid_observations(state, request_id)
        current = {name: project_observation(name, result) for name, result in valid.items()}
        latest_meta = {name: meta[name] for name in valid}
        review = current.get("check_rules", {})
        problem = (
            review.get("status")
            if review.get("status") in {"missing", "blocked"}
            else "conflict"
            if row["proposal"] or observations.get("save_draft", {}).get("conflict")
            else "conflict"
            if any(
                not slot["available"] and slot["time"] == row["body"]["requested_time"]
                for slot in current.get("query_slots", {}).get("slots", [])
            )
            else "normal"
            if review
            else "unknown"
        )
        stage = (
            "review"
            if not review
            else "blocked"
            if review.get("status") != "passed"
            else "schedule"
        )
        relevant = (
            {"read_material", "check_rules", "finish"}
            if stage in {"review", "blocked"}
            else {"check_rules", "query_slots", "save_draft"}
        )
        errors = [
            {"tool": name, "result": result, "source": meta.get(name, {})}
            for name, result in observations.items()
            if result.get("error") or result.get("conflict")
        ]
        errors.sort(key=lambda item: item["source"].get("source_step", -1))
        working = {
            "original_request": row["body"],
            "current_proposal": row["proposal"],
            "authorization_source": "business_database_only",
            "current_observations": {k: v for k, v in current.items() if k in relevant},
            "observation_sources": {k: v for k, v in latest_meta.items() if k in relevant},
            "read_material_completed": "read_material" in current,
            "review_requires_refresh": "check_rules" not in current,
            "slots_are_snapshot_only": True,
            "invalidated_observations": invalidated,
            "latest_errors": errors[-1:],
            "stage": stage,
            "generation": state.get("generation", 0),
            "budget_consumed": {k: row[k] for k in ("model_calls", "tool_calls", "active_seconds")},
        }
        cases = []
        memory_error = False
        try:
            for case in self.memory.search(
                row["body"], row["mode"], rules_version, problem, self.settings.memory_top_k
            ):
                # A persisted reference must still identify the actual source execution.
                try:
                    source = self.repo.get(case["source_request_id"])
                except BusinessError:
                    continue
                if (
                    source["run_id"] == case["source_run_id"]
                    and source["execution"] == case["outcome"]
                ):
                    cases.append(case)
        except (OSError, sqlite3.Error, json.JSONDecodeError):
            memory_error = True  # Advisory lookup cannot authorize or block business operations.
        pairs = exchanges(original)
        latest = {pair[1]["name"]: index for index, pair in enumerate(pairs)}
        eligible = [
            index
            for index, pair in enumerate(pairs)
            if pair[1]["name"] in current
            and pair[1]["name"] in relevant
            and latest[pair[1]["name"]] == index
        ]
        selected = set(eligible)
        # Keep recent errors too. Invalidated slot/old-generation pairs are never reintroduced.
        for index in range(max(0, len(pairs) - self.settings.context_recent_turns), len(pairs)):
            name = pairs[index][1]["name"]
            source = pairs[index][1].get("_context_source", {})
            result = json.loads(pairs[index][1]["content"])
            if (
                source.get("generation") == working["generation"]
                and name not in invalidated
                and (name in relevant or result.get("error") or result.get("conflict"))
            ):
                selected.add(index)
        previous_summary = state.get("summary", {})
        base = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(row["body"], ensure_ascii=False)},
        ]

        def assemble(indices, memories):
            dropped = [pair for index, pair in enumerate(pairs) if index not in indices]
            summary = summarize(previous_summary, dropped)
            packet = {
                "context_packet": {
                    "working_memory": working,
                    "summary": summary,
                    "historical_cases": memories,
                    "notice": "working_memory.current_observations是当前工具有效结果投影，"
                    "对应observation_sources，可作为后续动作依据；压缩工具消息不代表该工具未执行。"
                    "read_material_completed=true表示素材已读取，title_truncated=true仅表示标题正文省略。"
                    "review_requires_refresh=true表示还需check_rules，不代表必须重复read_material。"
                    "summary和historical_cases才是历史资料，仅供参考，不能授权或替代当前占用查询。"
                    "失效观察需重查，工具错误需处理，只有业务库提供用户确认。",
                }
            }
            history = [
                *base,
                *[m for index, pair in enumerate(pairs) if index in indices for m in pair],
            ]
            messages = [
                *base,
                {"role": "user", "content": json.dumps(packet, ensure_ascii=False)},
                *[{k: v for k, v in m.items() if not k.startswith("_")} for m in history[2:]],
            ]
            return messages, history, summary

        messages, history, summary = assemble(selected, cases)
        # At 80% of the configured proxy budget, compress older exchanges incrementally.
        target = int(self.settings.context_max_estimate * 0.8)
        omitted_memory = []
        while estimate_size(messages, tools) > target and cases:
            omitted_memory.append(cases.pop()["source_run_id"])
            messages, history, summary = assemble(selected, cases)
        while estimate_size(messages, tools) > target and selected:
            selected.remove(min(selected))
            messages, history, summary = assemble(selected, cases)
        after = estimate_size(messages, tools)
        if after > self.settings.context_max_estimate:
            raise BusinessError("上下文必要事实超过预算；未删除原要求、审核风险或授权，未调用模型")
        audit.update(
            {
                "after_estimate": after,
                "retained_pairs": len(selected),
                "dropped_pairs": len(pairs) - len(selected),
                "stage": stage,
                "memory_scope": {
                    "channel": row["body"]["channel"],
                    "account": row["body"]["account"],
                    "mode": row["mode"],
                    "rules_version": rules_version,
                    "problem": problem,
                },
                "summary_covered_pairs": summary["covered_pairs"],
                "invalidated_observations": invalidated,
                "memory_lookup_failed": memory_error,
                "retrieved_cases": [
                    {
                        k: c[k]
                        for k in (
                            "source_run_id",
                            "source_request_id",
                            "source_trace",
                            "retrieval_reason",
                            "score",
                        )
                    }
                    for c in cases
                ],
                "omitted_memory": omitted_memory,
                "summary_sources": [
                    v["source_call_id"] for v in summary["last_observation_by_tool"].values()
                ],
            }
        )
        return {
            "messages": messages,
            "history": history,
            "working_memory": working,
            "summary": summary,
            "audit": audit,
        }

    def observation_source(self, request_id: str, state: dict) -> dict:
        row = self.repo.get(request_id)
        return {
            "source_step": row["tool_calls"],
            "observed_at": datetime.now(UTC).isoformat(),
            "generation": state.get("generation", 0),
            "rules_version": self.catalog.rules_version(),
            "material_version": self.catalog.material_version(row["body"]["material_id"]),
        }
