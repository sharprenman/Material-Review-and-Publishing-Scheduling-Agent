"""Paired executions with real tools/data. No mock run is labelled as live evidence."""

import argparse
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from material_scheduler.bootstrap import create_service
from material_scheduler.config import Settings
from material_scheduler.domain.models import Confirmation, ScheduleRequest
from material_scheduler.infrastructure.model.deepseek import DeepSeek, ModelError
from material_scheduler.infrastructure.model.mock import MockModel
from material_scheduler.interfaces.presenters import trace_document

ROOT = Path(__file__).resolve().parents[1]


class CappedModel:
    def __init__(self, base):
        self.base = base
        self.mode, self.name = base.mode, base.name
        self.calls = 0
        self.last_metadata = {}

    def choose(self, messages, tools, timeout):
        self.last_metadata = {}
        if self.calls >= 60:
            raise ModelError("对比脚本总调用预算60次已耗尽")
        self.calls += 1
        try:
            return self.base.choose(messages, tools, timeout)
        finally:
            self.last_metadata = getattr(self.base, "last_metadata", {})


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def execute(mode: str, key_file=None, baseline_from=None):
    key = None
    if key_file:
        from generate_examples import local_key

        key = local_key(key_file)
    model = CappedModel(DeepSeek(key=key) if mode == "live" else MockModel())
    batch = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "examples" / "context-evaluation" / mode / batch
    output.mkdir(parents=True)
    results = {}
    reused = None
    if baseline_from:
        reused = json.loads((baseline_from / "manifest.json").read_text())
        if (
            reused["mode"] != mode
            or reused["model"] != model.name
            or reused["context_proxy_budget"] != 32000
            or reused["title_chars_long_case"] != 7000
        ):
            raise ValueError("基线模式、模型或数据配置不匹配")
    for strategy in ("baseline", "optimized"):
        folder = output / strategy
        folder.mkdir()
        if strategy == "baseline" and reused:
            shutil.copytree(baseline_from / "baseline", folder, dirs_exist_ok=True)
            results[strategy] = reused["results"]["baseline"]
            if not all(r["business_check_passed"] for r in results[strategy].values()):
                raise ValueError("引用基线未完成业务验证")
            continue
        runtime = ROOT / "var" / "context-evaluation" / mode / batch / strategy
        data = runtime / "data"
        shutil.copytree(ROOT / "data", data)
        materials = json.loads((data / "materials.json").read_text())
        materials.append(
            {"material_id": "M04", "title": "测试说明" * 1750, "rights": True, "tags": []}
        )
        write_json(data / "materials.json", materials)
        if reused:
            for name in ("materials.json", "rules.json", "schedules.json"):
                if json.loads((data / name).read_text()) != json.loads(
                    (baseline_from / "baseline/data" / name).read_text()
                ):
                    raise ValueError("本次资料与引用基线不一致")
        shutil.copytree(data, folder / "data")
        settings = Settings(
            data_dir=data,
            runtime_dir=runtime,
            mode=mode,
            context_enabled=strategy == "optimized",
            context_max_estimate=32000,
        )
        service = create_service(settings, model)
        results[strategy] = {}
        try:
            # A genuine earlier request supplies the cross-request case; it reserves no time slot.
            seed = ScheduleRequest(
                request_id="seed_missing",
                material_id="M02",
                channel="video",
                account="team",
                requested_time="2026-11-01T17:00:00+08:00",
            )
            write_json(folder / "seed_missing.input.json", seed.model_dump(mode="json"))
            seed_result = service.run(seed)
            write_json(folder / "seed_missing.output.json", seed_result.model_dump())
            shutil.copyfile(
                runtime / "traces" / f"{seed_result.run_id}.jsonl", folder / "seed_missing.jsonl"
            )
            service.close()
            service = create_service(settings, model)
            for name, material, hour in [
                ("normal", "M01", 17),
                ("missing", "M02", 17),
                ("conflict", "M01", 18),
                ("long_metadata", "M04", 16),
            ]:
                request = ScheduleRequest(
                    request_id=name,
                    material_id=material,
                    channel="video",
                    account="team",
                    requested_time=f"2026-11-01T{hour}:00:00+08:00",
                )
                write_json(folder / f"{name}.input.json", request.model_dump(mode="json"))
                started = monotonic()
                first = service.run(request)
                write_json(folder / f"{name}.initial.json", first.model_dump())
                result = first
                if name == "conflict" and first.execution == "waiting_confirmation":
                    p = first.proposal
                    service.close()
                    service = create_service(settings, model)
                    result = service.confirm(
                        name,
                        Confirmation(
                            proposal_id=p["proposal_id"], version=p["version"], accept=True
                        ),
                    )
                elapsed = round((monotonic() - started) * 1000)
                write_json(folder / f"{name}.output.json", result.model_dump())
                source = runtime / "traces" / f"{result.run_id}.jsonl"
                shutil.copyfile(source, folder / f"{name}.jsonl")
                events = [json.loads(line) for line in source.read_text().splitlines()]
                actions = [e for e in events if e["event"] == "model_action"]
                contexts = [e for e in events if e["event"] == "context_prepared"]
                usages = [
                    e["metadata"]["usage"] for e in actions if e.get("metadata", {}).get("usage")
                ]
                expected = "blocked" if name == "missing" else "completed"
                valid = result.execution == expected and (
                    result.review and result.review["status"] == "missing" and result.draft is None
                    if name == "missing"
                    else result.draft is not None
                    and result.draft["time"].endswith(
                        f"{19 if name == 'conflict' else hour}:00:00+08:00"
                    )
                )
                metric = {
                    "execution": result.execution,
                    "business_check_passed": bool(valid),
                    "model_calls": result.model_calls,
                    "tool_calls": result.tool_calls,
                    "elapsed_ms": elapsed,
                    "reported_prompt_tokens": sum(u["prompt_tokens"] for u in usages)
                    if usages
                    else None,
                    "reported_completion_tokens": sum(u["completion_tokens"] for u in usages)
                    if usages
                    else None,
                    "usage_complete": bool(usages) and len(usages) == result.model_calls,
                    "max_context_estimate": max(
                        (c["after_estimate"] for c in contexts), default=None
                    ),
                    "compressed_pairs": sum(c["dropped_pairs"] for c in contexts),
                    "retrieved_source_requests": sorted(
                        {
                            c["source_request_id"]
                            for event in contexts
                            for c in event["retrieved_cases"]
                        }
                    ),
                    "database_draft": service.repo.draft(name),
                }
                results[strategy][name] = metric
                write_json(folder / f"{name}.metrics.json", metric)
                (folder / f"{name}.md").write_text(
                    trace_document(events, name, markdown=True) + "\n"
                )
                print(
                    json.dumps(
                        {"mode": mode, "strategy": strategy, "case": name, **metric},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        finally:
            service.close()
    comparisons = {}
    for name in results["baseline"]:
        before, after = results["baseline"][name], results["optimized"][name]
        comparable = before["business_check_passed"] and after["business_check_passed"]
        tokens = None
        if comparable and before["usage_complete"] and after["usage_complete"]:
            tokens = round(
                (1 - after["reported_prompt_tokens"] / before["reported_prompt_tokens"]) * 100, 2
            )
        comparisons[name] = {
            "both_business_checks_passed": comparable,
            "prompt_token_reduction_percent": tokens,
            "note": "负数代表优化版输入更多；单次样本，不代表稳定收益",
        }
    manifest = {
        "mode": mode,
        "model": model.name,
        "batch_utc": batch,
        "calls_including_seed": model.calls,
        "call_cap": 60,
        "reused_baseline_batch": reused["batch_utc"] if reused else None,
        "context_proxy_budget": 32000,
        "title_chars_long_case": 7000,
        "results": results,
        "comparisons": comparisons,
        "method": "同请求与合成资料，两套独立数据库；各自真实执行前置缺资料请求并重启；无自动重试",
    }
    write_json(output / "manifest.json", manifest)
    report = [
        "# 上下文工程执行对比",
        "",
        f"模式：{mode}；模型：{model.name}；批次：{batch}（UTC）。",
        "同一输入各跑一次，模型有随机性；输入token来自API usage，非大小代理估算。",
        f"引用基线批次：{reused['batch_utc'] if reused else '本次执行'}；"
        f"本批实际新增调用：{model.calls}（含前置请求）。",
        "缺资料历史案例来自各自真实前置请求，不复制Mock结果；案例不授予当前请求任何权限。",
        "",
        "| 场景 | 基线/优化版结果 | 输入token：基线→优化 | 输入减少比例 | 模型调用：基线→优化 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, comparison in comparisons.items():
        a, b = results["baseline"][name], results["optimized"][name]
        report.append(
            f"| {name} | {a['execution']} / {b['execution']} | "
            f"{a['reported_prompt_tokens']} → {b['reported_prompt_tokens']} | "
            f"{comparison['prompt_token_reduction_percent']}% | "
            f"{a['model_calls']} → {b['model_calls']} |"
        )
    report.extend(
        [
            "",
            "负数表示输入增加。短路径的结构化状态与来源信息可能增加输入，不能预先承诺收益。",
            "完整输出、数据库草稿事实、模型响应ID、usage与上下文筛选记录均在同目录。",
        ]
    )
    for name in comparisons:
        a, b = results["baseline"][name], results["optimized"][name]
        report.extend(
            [
                "",
                f"[基线{name}过程](baseline/{name}.md) · [优化版{name}过程](optimized/{name}.md)",
                f"耗时：{a['elapsed_ms']}→{b['elapsed_ms']}ms；工具调用：{a['tool_calls']}→{b['tool_calls']}。",
            ]
        )
    (output / "README.md").write_text("\n".join(report) + "\n")
    (output.parent / "README.md").write_text(
        f"# 最新{mode}上下文对比\n\n[查看本次对比]({batch}/README.md)\n"
    )
    print(f"对比入口：{output / 'README.md'}", flush=True)
    return all(c["both_business_checks_passed"] for c in comparisons.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--key-file", type=Path)
    parser.add_argument(
        "--baseline-from", type=Path, help="复用同模式、同模型、同资料的真实基线，来源写入manifest"
    )
    args = parser.parse_args()
    raise SystemExit(0 if execute(args.mode, args.key_file, args.baseline_from) else 1)
