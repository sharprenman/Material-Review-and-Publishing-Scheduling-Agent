"""Read-only summaries of recorded observations; never invent model explanations."""

import json

TOOL_NAMES = {
    "read_material": "读取素材",
    "check_rules": "规则审核",
    "query_slots": "查询时段",
    "save_draft": "保存草稿或提出方案",
    "finish": "结束处理",
    "context_prepared": "上下文组装",
    "context_failure": "上下文失败",
}
ROUTES = {"decide": "等待模型选择下一步", "confirm": "等待用户确认", "end": "结束"}
MISSING_NAMES = {"material": "素材", "title": "标题", "rights": "使用权信息"}


def result_summary(tool: str, result: dict) -> str:
    if result.get("error"):
        return result["error"]
    if tool == "read_material":
        if result.get("material") is None:
            return "素材不存在"
        missing = "、".join(MISSING_NAMES.get(k, k) for k in result.get("missing", []))
        return "素材已读取；缺失项：" + (missing or "无")
    if tool == "check_rules" or "review" in result:
        review = result.get("review", result)
        missing = "、".join(MISSING_NAMES.get(k, k) for k in review.get("missing", []))
        risks = "；".join(f"{r['rule_id']}：{r['reason']}" for r in review.get("risks", []))
        return {
            "passed": "审核通过",
            "missing": "资料不足：" + missing,
            "blocked": "审核阻断：" + risks,
        }.get(review.get("status"), "审核结果未知")
    if tool == "query_slots":
        return (
            "；".join(
                f"{s['time']} {'可用' if s['available'] else '已占用'}"
                for s in result.get("slots", [])
            )
            or "无候选时段"
        )
    if result.get("saved"):
        return f"草稿已保存，时间：{result['draft']['time']}"
    if result.get("proposal"):
        return f"方案时间：{result['proposal']['time']}；待确认，未保存草稿"
    if result.get("conflict"):
        return "保存前发现最新占用变化，未保存"
    return {
        "missing": "资料不足，结束",
        "blocked": "规则风险，结束",
        "no_slots": "无可用时段，结束",
        "incomplete": "执行未完成",
    }.get(result.get("reason", ""), json.dumps(result, ensure_ascii=False))


def policy_explanation(tool: str, result: dict, route: str) -> str:
    if result.get("error"):
        return "工具前置条件未满足，不能执行保存或绕过规则。"
    if result.get("saved"):
        return "事务校验通过，保存状态以数据库草稿为准；没有执行发布。"
    if result.get("proposal"):
        return "替代原要求时间必须取得用户确认；目前只持久化待确认方案。"
    if result.get("conflict"):
        return "最新占用检查失败，不能保存旧候选，需重新查询。"
    if tool == "check_rules" or "review" in result:
        review = result.get("review", result)
        return (
            "资料缺失或硬规则风险不能绕过。"
            if review.get("status") != "passed"
            else ("审核通过；保存前仍会复核审核与占用。")
        )
    if tool == "query_slots":
        return "候选来自当前业务库；待确认方案不占位，草稿占位。"
    if tool == "read_material":
        return "只读取素材事实，不补造缺失信息。"
    return "结束不代表保存；最终保存状态以数据库为准。"


def trace_steps(events: list[dict]) -> list[dict]:
    rows = []
    for index, event in enumerate(events):
        kind = event.get("event")
        if kind == "model_action":
            subsequent = []
            for following in events[index + 1 :]:
                if following.get("event") in {"model_action", "user_confirmation"}:
                    break
                subsequent.append(following)
            result_event = next((e for e in subsequent if e.get("event") == "tool_result"), None)
            failure = next((e for e in subsequent if e.get("event") == "tool_failure"), None)
            next_action = "未执行或无工具返回"
            summary = "无已记录的工具结果"
            policy = "无已记录的程序说明"
            if result_event:
                result = result_event.get("result", {})
                summary = result_event.get("result_summary") or result_summary(
                    event["tool"], result
                )
                route = result_event.get("next_action", "")
                next_action = ROUTES.get(route, route)
                if route == "decide":
                    next_model = next(
                        (
                            e
                            for e in events[index + 1 :]
                            if e.get("event") in {"model_action", "model_failure"}
                        ),
                        None,
                    )
                    if next_model:
                        next_action = (
                            "模型选择：" + TOOL_NAMES.get(next_model["tool"], next_model["tool"])
                            if next_model["event"] == "model_action"
                            else "模型调用失败，结束"
                        )
                policy = (
                    result_event.get("rationale", "")
                    if result_event.get("rationale_source") == "program_policy"
                    else "依据旧工具结果生成的摘要："
                    + policy_explanation(event["tool"], result, route)
                )
            elif failure:
                summary, next_action, policy = "工具执行失败", "结束", "不能宣称保存成功。"
            source = event.get("rationale_source", "legacy_unavailable")
            basis = (
                event.get("rationale", "未记录")
                if source in {"model", "offline_model"}
                else "旧记录未提供具体模型依据；不补写模型原话。"
            )
            rows.append(
                {
                    "step": event.get("step"),
                    "tool": event["tool"],
                    "arguments": event.get("arguments", {}),
                    "result_summary": summary,
                    "next_action": next_action,
                    "model_rationale": basis,
                    "rationale_source": source,
                    "program_explanation": policy,
                }
            )
        elif kind == "context_prepared":
            cases = event.get("retrieved_cases", [])
            lookup = (
                "；".join(f"{c['source_request_id']}（{c['retrieval_reason']}）" for c in cases)
                or "无"
            )
            if event.get("memory_lookup_failed"):
                lookup = "记忆查询不可用；已继续处理当前请求"
            rows.append(
                {
                    "step": "—",
                    "tool": kind,
                    "arguments": {},
                    "result_summary": f"保留{event['retained_pairs']}对交互；"
                    f"压缩{event['dropped_pairs']}对；"
                    f"大小估算{event['before_estimate']}→{event['after_estimate']}（非精确token）；案例：{lookup}",
                    "next_action": "模型选择下一动作",
                    "model_rationale": "不适用（程序组装）",
                    "rationale_source": "program_event",
                    "program_explanation": "原始要求与授权来自业务库；"
                    "摘要和历史案例不提供保存权限。",
                }
            )
        elif kind in {
            "model_failure",
            "context_failure",
            "user_confirmation",
            "tool_budget_exhausted",
            "memory_write_failed",
        }:
            rows.append(
                {
                    "step": "—",
                    "tool": kind,
                    "arguments": event.get("proposal", {}),
                    "result_summary": event.get(
                        "error",
                        "历史案例写入失败，业务状态不受影响"
                        if kind == "memory_write_failed"
                        else "用户确认已登记；恢复后重新审核与查询",
                    ),
                    "next_action": ROUTES.get(event.get("next_action", ""), "结束"),
                    "model_rationale": "不适用（程序/用户事件）",
                    "rationale_source": "program_event",
                    "program_explanation": "按实际事件记录。",
                }
            )
    return rows
