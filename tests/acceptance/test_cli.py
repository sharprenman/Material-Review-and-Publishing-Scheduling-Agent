from conftest import request
from typer.testing import CliRunner

from material_scheduler.interfaces.cli import app


def test_cli(settings, tmp_path):
    file = tmp_path / "input.json"
    file.write_text(request().model_dump_json())
    runner = CliRunner()
    prefix = ["--data-dir", str(settings.data_dir), "--runtime-dir", str(settings.runtime_dir)]
    result = runner.invoke(app, [*prefix, "run", str(file), "--json"])
    assert result.exit_code == 0, result.output
    assert '"save_status": "saved"' in result.output
    assert runner.invoke(app, [*prefix, "draft", "normal"]).exit_code == 0
    assert runner.invoke(app, [*prefix, "status", "unknown"]).exit_code == 4


def test_readable_confirmation_and_copyable_command(settings, tmp_path):
    import json
    import shlex

    file = tmp_path / "conflict.json"
    file.write_text(request(hour=18).model_dump_json())
    runner = CliRunner()
    prefix = ["--data-dir", str(settings.data_dir), "--runtime-dir", str(settings.runtime_dir)]
    pending = runner.invoke(app, [*prefix, "run", str(file)])
    assert pending.exit_code == 2
    assert "等待你确认" in pending.output and "尚未保存草稿" in pending.output
    command = pending.output.split("确认命令：\n")[1].splitlines()[0]
    arguments = shlex.split(command)[3:]
    confirmed = runner.invoke(app, arguments)
    assert confirmed.exit_code == 0, confirmed.output
    assert "草稿已保存（未发布）" in confirmed.output
    result = runner.invoke(app, [*prefix, "status", "normal", "--json"])
    assert json.loads(result.output)["draft"]["time"].endswith("19:00:00+08:00")
    trace = runner.invoke(app, [*prefix, "trace", "normal"])
    assert trace.exit_code == 0, trace.output
    assert "离线替身说明" in trace.output and "程序说明" in trace.output
    assert "18:00:00+08:00 已占用" in trace.output
    assert "19:00:00+08:00 可用" in trace.output


def test_global_json_and_error_modes(settings, tmp_path):
    import json

    file = tmp_path / "input.json"
    file.write_text(request().model_dump_json())
    runner = CliRunner()
    prefix = ["--data-dir", str(settings.data_dir), "--runtime-dir", str(settings.runtime_dir)]
    result = runner.invoke(app, [*prefix, "--json", "run", str(file)])
    assert result.exit_code == 0 and json.loads(result.output)["save_status"] == "saved"
    missing = runner.invoke(app, [*prefix, "status", "unknown", "--json"])
    assert missing.exit_code == 4 and "error" in json.loads(missing.output)
    trace = runner.invoke(app, [*prefix, "trace", "normal", "--json"])
    steps = json.loads(trace.output)["steps"]
    assert any(step["rationale_source"] == "offline_model" for step in steps)
    assert steps[0]["tool"] == "context_prepared"


def test_old_trace_readonly_without_key(tmp_path, monkeypatch):
    import json

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    source = tmp_path / "legacy.jsonl"
    events = [
        {
            "request_id": "old",
            "mode": "live",
            "event": "model_action",
            "step": 1,
            "tool": "query_slots",
            "arguments": {},
            "rationale": "模型实际返回的工具选择",
        },
        {
            "request_id": "old",
            "mode": "live",
            "event": "tool_result",
            "step": 1,
            "tool": "query_slots",
            "result": {"slots": []},
            "next_action": "decide",
        },
    ]
    contents = "\n".join(json.dumps(e) for e in events)
    source.write_text(contents)
    runner = CliRunner()
    result = runner.invoke(
        app, ["--mode", "live", "--data-dir", "absent-data", "trace", "old", "--file", str(source)]
    )
    assert result.exit_code == 0, result.output
    assert "旧记录未提供具体模型依据" in result.output
    assert "依据旧工具结果生成的摘要" in result.output
    assert source.read_text() == contents
    wrong = runner.invoke(app, ["trace", "other", "--file", str(source)])
    assert wrong.exit_code == 4


def test_context_budget_exhaustion_does_not_call_model(settings, tmp_path):
    import json

    file = tmp_path / "input.json"
    file.write_text(request().model_dump_json())
    runner = CliRunner()
    prefix = [
        "--data-dir",
        str(settings.data_dir),
        "--runtime-dir",
        str(settings.runtime_dir),
        "--context-budget",
        "512",
    ]
    result = runner.invoke(app, [*prefix, "run", str(file), "--json"])
    assert result.exit_code == 4
    body = json.loads(result.output)
    assert body["execution"] == "incomplete" and body["model_calls"] == body["tool_calls"] == 0
    assert "必要事实超过预算" in body["error"] and body["draft"] is None
    trace = runner.invoke(app, [*prefix, "trace", "normal"])
    assert trace.exit_code == 0 and "上下文失败" in trace.output


def test_json_stdout_survives_trace_failure(settings, tmp_path, monkeypatch):
    import json
    from pathlib import Path

    original = Path.open

    def fail_audit(path, *args, **kwargs):
        if path.suffix == ".jsonl":
            raise OSError("controlled audit failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_audit)
    file = tmp_path / "input.json"
    file.write_text(request().model_dump_json())
    result = CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(settings.data_dir),
            "--runtime-dir",
            str(settings.runtime_dir),
            "run",
            str(file),
            "--json",
        ],
    )
    assert result.exit_code == 0
    body = json.loads(result.stdout)
    assert body["execution"] == "completed" and body["error"] is None
    assert "审计警告" in result.stderr
