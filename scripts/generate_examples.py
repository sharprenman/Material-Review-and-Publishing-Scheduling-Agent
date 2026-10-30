"""Execute isolated real workflows; model fixtures are explicitly labelled mock."""

import argparse
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from material_scheduler.bootstrap import create_service
from material_scheduler.config import Settings
from material_scheduler.domain.models import Confirmation, ScheduleRequest
from material_scheduler.infrastructure.model.deepseek import DeepSeek, ModelError
from material_scheduler.infrastructure.model.mock import MockModel
from material_scheduler.interfaces.presenters import STATUSES, trace_document

ROOT = Path(__file__).resolve().parents[1]


def local_key(path):
    # macOS-only opt-in helper. Captured text remains in memory, never printed or saved.
    raw = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    match = re.search(r"sk-[A-Za-z0-9_-]{16,}", raw)
    if not match:
        raise ValueError("本地文件没有可解析凭证")
    return match.group(0)


class CappedLive(DeepSeek):
    calls = 0

    def choose(self, messages, tools, timeout):
        if self.calls >= 36:
            raise ModelError("证据脚本真实调用总上限36次")
        self.calls += 1
        return super().choose(messages, tools, timeout)


def generate(mode, key_file=None):
    model = (
        CappedLive(key=local_key(key_file) if key_file else None) if mode == "live" else MockModel()
    )
    batch = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    runtime = ROOT / "var" / "evidence" / f"{mode}-{batch}"
    out = ROOT / "examples" / "outputs" / mode
    trace = ROOT / "examples" / "traces" / mode
    for directory in (out, trace):
        if directory.exists():
            archive = directory.parent / "history" / f"{mode}-before-{batch}"
            archive.parent.mkdir(exist_ok=True)
            shutil.move(str(directory), str(archive))
        directory.mkdir(parents=True, exist_ok=True)
    summary = []
    for name, material, hour in [
        ("normal", "M01", 17),
        ("missing", "M02", 17),
        ("risk", "M03", 17),
        ("conflict", "M01", 18),
        ("changed", "M01", 18),
        ("save_failure", "M01", 17),
    ]:
        request = ScheduleRequest(
            request_id=name,
            material_id=material,
            channel="video",
            account="team",
            requested_time=f"2026-11-01T{hour}:00:00+08:00",
        )
        (ROOT / "examples" / "inputs" / f"{name}.json").write_text(
            request.model_dump_json(indent=2) + "\n"
        )
        settings = Settings(data_dir=ROOT / "data", runtime_dir=runtime / name, mode=mode)
        service = create_service(settings, model)
        try:
            if name == "changed":
                with service.repo.db:
                    service.repo.db.execute(
                        "INSERT INTO slots VALUES('video','team',?, 'evidence')",
                        ("2026-11-01T19:00:00+08:00",),
                    )
            if name == "save_failure":
                service.repo.db.executescript("""
                CREATE TRIGGER fail_draft BEFORE INSERT ON drafts
                BEGIN SELECT RAISE(ABORT,'controlled write failure'); END;
                """)
            result = service.run(request)
            (out / f"{name}.json").write_text(result.model_dump_json(indent=2) + "\n")
            expected = {
                "normal": "completed",
                "missing": "blocked",
                "risk": "blocked",
                "conflict": "waiting_confirmation",
                "changed": "waiting_confirmation",
                "save_failure": "failed",
            }
            assert result.execution == expected[name], f"{name}: {result.execution}"
            if name in {"conflict", "changed"}:
                hour_expected = "19:00:00+08:00" if name == "conflict" else "20:00:00+08:00"
                assert result.proposal["time"].endswith(hour_expected)
                assert result.draft is None
            summary.append(
                {
                    "case": name,
                    "execution": result.execution,
                    "model_calls": result.model_calls,
                    "tool_calls": result.tool_calls,
                }
            )
            if name == "normal":
                duplicate = service.run(request)
                assert duplicate.draft == result.draft
                (out / "duplicate.json").write_text(duplicate.model_dump_json(indent=2) + "\n")
            if name == "conflict" and result.execution == "waiting_confirmation":
                proposal = result.proposal
                service.close()
                service = create_service(settings, model)
                result = service.confirm(
                    name,
                    Confirmation(
                        proposal_id=proposal["proposal_id"],
                        version=proposal["version"],
                        accept=True,
                    ),
                )
                assert result.execution == "completed" and result.draft is not None
                (out / "confirmed_after_restart.json").write_text(
                    result.model_dump_json(indent=2) + "\n"
                )
            facts = {
                "draft": service.repo.draft(name),
                "reservations": [
                    dict(r)
                    for r in service.repo.db.execute(
                        "SELECT * FROM slots ORDER BY channel,account,time"
                    )
                ],
                "draft_count": service.repo.db.execute("SELECT count(*) FROM drafts").fetchone()[0],
            }
            if name == "save_failure":
                assert facts["draft"] is None and facts["draft_count"] == 0
                assert not any(r["owner"] == name for r in facts["reservations"])
            (out / f"{name}_database.json").write_text(
                json.dumps(facts, ensure_ascii=False, indent=2) + "\n"
            )
            print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
        finally:
            row = service.repo.get(name)
            source = settings.runtime_dir / "traces" / f"{row['run_id']}.jsonl"
            if source.exists():
                shutil.copyfile(source, trace / f"{name}.jsonl")
            service.close()
    manifest = {
        "mode": mode,
        "batch_utc": batch,
        "isolation": "每个用例独立业务库及检查点库",
        "model": model.name,
        "real_call_cap": 36 if mode == "live" else None,
        "real_calls": getattr(model, "calls", 0),
        "save_failure": "真实SQLite触发器注入写失败并验证回滚；非真实磁盘故障",
        "changed": "在初始18点占用之外，真实插入19点占用，再执行模型流程",
        "cases": summary,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    write_report(mode, out, trace, manifest)


def write_report(mode, out, trace, manifest):
    """Render only existing facts; never changes outputs, traces or model evidence."""
    report = ROOT / "examples" / "reports" / f"{mode}.md"
    report.parent.mkdir(exist_ok=True)
    lines = [
        f"# {'真实模型' if mode == 'live' else '离线测试'}运行记录导读",
        "",
        f"批次：{manifest['batch_utc']}（UTC）｜模型：{manifest['model']}",
        "",
        "先看每条路径的结果，再看表格。模型依据是动作附带的简短自述，不是内部思维过程；程序说明单独列出。",
        "冲突用例由验证脚本自动模拟用户确认，并重建应用后继续；实际使用时需运行确认命令。",
        "",
        "| 路径 | 工具观察 | 后续行为 |",
        "| --- | --- | --- |",
        "| 正常 | 审核通过，17点可用 | 选择17点并保存草稿 |",
        "| 冲突 | 18点占用，19点可用 | 选择19点，等待确认；确认后重查并保存 |",
        "| 缺资料 | 缺少使用权信息 | 结束处理，不继续查询与保存 |",
    ]
    for name, title in [
        ("normal", "正常排期"),
        ("conflict", "冲突与确认"),
        ("missing", "资料不足"),
    ]:
        result = json.loads((out / f"{name}.json").read_text())
        events = [json.loads(line) for line in (trace / f"{name}.jsonl").read_text().splitlines()]
        lines.extend(
            [
                "",
                f"## {title}",
                "",
                f"原要求：{result['requested_time']}；执行：{STATUSES[result['execution']]}；"
                + ("草稿已保存。" if result["save_status"] == "saved" else "尚未保存草稿。"),
                f"[输入](../inputs/{name}.json) · [结果](../outputs/{mode}/{name}.json) · "
                f"[原始记录](../traces/{mode}/{name}.jsonl)",
                "",
                trace_document(events, name, markdown=True),
            ]
        )
        if name == "conflict":
            final = json.loads((out / "confirmed_after_restart.json").read_text())
            lines.extend(
                [
                    "",
                    "上面的结果链接为首次待确认快照；表格还包含脚本模拟确认后的步骤。",
                    f"确认后：{STATUSES[final['execution']]}，草稿时间：{final['draft']['time']}。",
                    f"[确认后的最终结果](../outputs/{mode}/confirmed_after_restart.json)",
                ]
            )
    report.write_text("\n".join(lines) + "\n")
    print(f"阅读入口：{report.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["mock", "live"], default="mock")
    parser.add_argument("--key-file", type=Path, help="可选：macOS本地RTF；默认环境变量")
    args = parser.parse_args()
    generate(args.mode, args.key_file)
