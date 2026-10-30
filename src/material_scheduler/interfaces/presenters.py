import json
import shlex

from material_scheduler.application.trace_view import MISSING_NAMES, TOOL_NAMES, trace_steps

STATUSES = {
    "completed": "执行完成",
    "waiting_confirmation": "等待你确认",
    "blocked": "审核阻断",
    "rejected": "用户已拒绝",
    "failed": "执行失败",
    "incomplete": "执行未完成",
    "running": "执行中",
}


def confirmation_command(result: dict, settings, accept: bool) -> str:
    proposal = result["proposal"]
    return shlex.join(
        [
            "uv",
            "run",
            "material-scheduler",
            "--data-dir",
            str(settings.data_dir),
            "--runtime-dir",
            str(settings.runtime_dir),
            "--mode",
            result["mode"],
            "--context-budget",
            str(settings.context_max_estimate),
            "--memory-top-k",
            str(settings.memory_top_k),
            "--context" if settings.context_enabled else "--baseline-context",
            "confirm",
            result["request_id"],
            proposal["proposal_id"],
            str(proposal["version"]),
            "--accept" if accept else "--reject",
        ]
    )


def present_result(result: dict, settings) -> str:
    review = result.get("review") or {}
    proposal = result.get("proposal") or {}
    draft = result.get("draft") or {}
    mode = "真实模型" if result["mode"] == "live" else "离线测试"
    lines = [
        f"请求：{result['request_id']}｜模式：{mode}",
        "审核："
        + {"passed": "通过", "missing": "资料不足", "blocked": "风险阻断"}.get(
            review.get("status", ""), "尚未完成"
        ),
        f"原要求：{result['requested_time']}",
    ]
    if review.get("missing"):
        lines.append("缺失项：" + "、".join(MISSING_NAMES.get(k, k) for k in review["missing"]))
    for risk in review.get("risks", []):
        lines.append(f"风险：{risk['rule_id']}｜{risk['reason']}")
    if proposal:
        lines.append(
            f"建议时间：{proposal['time']}｜确认："
            + {"pending": "待确认", "accepted": "已同意", "rejected": "已拒绝"}[
                proposal["confirmation"]
            ]
        )
    lines.append("执行状态：" + STATUSES.get(result["execution"], result["execution"]))
    lines.append(
        "保存状态："
        + {"saved": "草稿已保存（未发布）", "not_saved": "尚未保存草稿", "failed": "保存失败"}[
            result["save_status"]
        ]
    )
    if draft:
        lines.extend([f"草稿时间：{draft['time']}", f"草稿编号：{draft['draft_id']}"])
    if result.get("error"):
        lines.append("原因：" + result["error"])
    if proposal.get("confirmation") == "pending" and result["execution"] == "waiting_confirmation":
        lines.extend(
            [
                "程序说明：替代原要求时间需要你的确认，目前未保存草稿。",
                "确认命令：\n" + confirmation_command(result, settings, True),
                "拒绝命令：\n" + confirmation_command(result, settings, False),
            ]
        )
    lines.append(
        "查看过程："
        + shlex.join(
            [
                "uv",
                "run",
                "material-scheduler",
                "--data-dir",
                str(settings.data_dir),
                "--runtime-dir",
                str(settings.runtime_dir),
                "trace",
                result["request_id"],
            ]
        )
    )
    return "\n".join(lines)


def trace_document(events: list[dict], request_id: str, markdown: bool = False) -> str:
    mode = events[0].get("mode", "unknown") if events else "unknown"
    mode = {"live": "真实模型", "mock": "离线测试"}.get(mode, mode)
    lines = [
        f"请求：{request_id}｜模式：{mode}",
        "模型依据为动作附带的简短自述，未独立验证；程序说明来自确定性规则。",
    ]
    rows = trace_steps(events)
    if not rows:
        return "\n".join([*lines, "暂无执行记录。"])
    if markdown:
        lines.extend(
            [
                "",
                "| 步骤 | 工具 | 参数 | 返回摘要 | 后续动作 | 模型依据及来源 | 程序说明 |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
    for row in rows:
        source = {
            "model": "真实模型自述",
            "offline_model": "离线替身说明",
            "legacy_unavailable": "旧记录，缺少模型依据",
            "program_event": "程序/用户事件",
        }[row["rationale_source"]]
        title = TOOL_NAMES.get(row["tool"], row["tool"])
        values = [
            str(row["step"]),
            f"{title}（{row['tool']}）",
            json.dumps(row["arguments"], ensure_ascii=False),
            row["result_summary"],
            row["next_action"],
            f"[{source}] {row['model_rationale']}",
            row["program_explanation"],
        ]
        if markdown:
            lines.append(
                "| "
                + " | ".join(v.replace("|", "\\|").replace("\n", "<br>") for v in values)
                + " |"
            )
        else:
            lines.extend(
                [
                    "",
                    f"步骤 {values[0]}｜{values[1]}",
                    f"参数：{values[2]}",
                    f"返回摘要：{values[3]}",
                    f"后续动作：{values[4]}",
                    f"模型依据：{values[5]}",
                    f"程序说明：{values[6]}",
                ]
            )
    return "\n".join(lines)
