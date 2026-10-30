import json
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

import typer
from pydantic import ValidationError

from material_scheduler.application.trace_view import trace_steps
from material_scheduler.bootstrap import create_service
from material_scheduler.config import Settings
from material_scheduler.domain.errors import BusinessError, ModelError
from material_scheduler.domain.models import Confirmation, ScheduleRequest
from material_scheduler.interfaces.presenters import present_result, trace_document

app = typer.Typer(help="素材审核排期：仅保存草稿，绝不发布", no_args_is_help=True)


def output(value):
    typer.echo(json.dumps(value, ensure_ascii=False, indent=2))


@app.callback()
def configure(
    ctx: typer.Context,
    data_dir: Path = Path("data"),
    runtime_dir: Path = Path("var"),
    mode: Literal["mock", "live"] = "mock",
    json_output: Annotated[bool, typer.Option("--json", help="输出稳定JSON")] = False,
    context_budget: Annotated[
        int,
        typer.Option(
            "--context-budget", min=512, max=128000, help="上下文大小估算上限，并非精确token数"
        ),
    ] = 16000,
    memory_top_k: Annotated[int, typer.Option("--memory-top-k", min=0, max=5)] = 3,
    context_enabled: Annotated[
        bool, typer.Option("--context/--baseline-context", help="启用上下文优化；baseline仅供对比")
    ] = True,
):
    ctx.meta["json_output"] = json_output
    ctx.obj = Settings(
        data_dir=data_dir,
        runtime_dir=runtime_dir,
        mode=mode,
        context_max_estimate=context_budget,
        memory_top_k=memory_top_k,
        context_enabled=context_enabled,
    )


def execute(ctx, operation, json_output=False, service_needed=True):
    service = None
    try:
        service = create_service(ctx.obj) if service_needed else None
        result = operation(service)
        machine = json_output or ctx.meta.get("json_output", False)
        if isinstance(result, dict):
            if machine:
                output({**result, "steps": trace_steps(result["events"])})
            else:
                typer.echo(trace_document(result["events"], result["request_id"]))
            return
        if machine:
            output(result.model_dump())
        else:
            typer.echo(present_result(result.model_dump(), ctx.obj))
        codes = {
            "completed": 0,
            "waiting_confirmation": 2,
            "blocked": 3,
            "rejected": 3,
            "failed": 4,
            "incomplete": 4,
        }
        raise typer.Exit(codes.get(result.execution, 4))
    except (BusinessError, ModelError) as exc:
        if json_output or ctx.meta.get("json_output", False):
            output({"error": str(exc)})
        else:
            typer.echo("处理失败：" + str(exc))
        raise typer.Exit(4) from None
    except (OSError, sqlite3.Error, ValidationError, ValueError, KeyError, TypeError):
        if json_output or ctx.meta.get("json_output", False):
            output({"error": "输入或配置无效，请检查资料文件和参数"})
        else:
            typer.echo("处理失败：输入或配置无效，请检查资料文件和参数")
        raise typer.Exit(4) from None
    finally:
        if service:
            service.close()


@app.command()
def run(
    ctx: typer.Context,
    input_file: Path,
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    def operation(service):
        return service.run(ScheduleRequest.model_validate_json(input_file.read_text()))

    execute(ctx, operation, json_output)


@app.command()
def confirm(
    ctx: typer.Context,
    request_id: str,
    proposal_id: str,
    version: int,
    accept: Annotated[bool, typer.Option("--accept/--reject")] = True,
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    execute(
        ctx,
        lambda s: s.confirm(
            request_id, Confirmation(proposal_id=proposal_id, version=version, accept=accept)
        ),
        json_output,
    )


@app.command()
def status(
    ctx: typer.Context,
    request_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    execute(ctx, lambda s: s.status(request_id), json_output)


@app.command()
def draft(
    ctx: typer.Context,
    request_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    execute(ctx, lambda s: s.status(request_id), json_output)


@app.command()
def trace(
    ctx: typer.Context,
    request_id: str,
    file: Annotated[Path | None, typer.Option("--file", help="读取已有JSONL，不调用模型")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
):
    """查看步骤、工具参数、实际观察、下一动作与有来源的依据。"""

    def operation(service):
        if file is None:
            return service.trace(request_id)
        events = [json.loads(line) for line in file.read_text().splitlines() if line.strip()]
        if any(not isinstance(e, dict) or e.get("request_id") != request_id for e in events):
            raise BusinessError("记录不属于指定请求")
        return {
            "request_id": request_id,
            "mode": events[0].get("mode", "unknown") if events else "unknown",
            "events": events,
        }

    execute(ctx, operation, json_output, service_needed=file is None)
