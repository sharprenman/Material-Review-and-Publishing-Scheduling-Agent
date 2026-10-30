"""No response body, header or credential is included in errors or traces."""

import json
import os
import re
from pathlib import Path

import httpx
from dotenv import load_dotenv

from material_scheduler.application.tools import ActionRationale
from material_scheduler.domain.errors import ModelError


class DeepSeek:
    mode = "live"

    def __init__(self, key: str | None = None, name: str | None = None):
        load_dotenv(Path.cwd() / ".env", override=False)
        self.key = key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.name = name or os.environ.get("DEEPSEEK_MODEL", "deepseek-flash")
        if not self.key:
            raise ModelError("缺少 DEEPSEEK_API_KEY；请在本地设置")
        self.last_metadata: dict = {}

    def choose(self, messages: list[dict], tools: list[dict], timeout: float) -> dict:
        self.last_metadata = {}
        try:
            response = httpx.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {self.key}"},
                json={
                    "model": self.name,
                    "messages": messages,
                    "tools": tools,
                    "thinking": {"type": "disabled"},
                    "max_tokens": 800,
                    "stream": False,
                },
                timeout=timeout,
            )
            if response.status_code != 200:
                raise ModelError(f"DeepSeek HTTP {response.status_code}")
            body = response.json()
            self.last_metadata = {k: body.get(k) for k in ("id", "model", "usage")}
            message = body["choices"][0]["message"]
            calls = message.get("tool_calls") or []
            if len(calls) != 1:
                raise ModelError("模型必须一次返回一个工具动作")
            call = calls[0]
            arguments = json.loads(call["function"]["arguments"])
            if not isinstance(arguments, dict):
                raise ModelError("工具参数必须为对象")
            rationale = ActionRationale(rationale=arguments.pop("rationale", None)).rationale
            rationale = re.sub(
                r"sk-[A-Za-z0-9_-]+", "[已脱敏]", rationale.replace(self.key, "[已脱敏]")
            )
            return {
                "id": call["id"],
                "name": call["function"]["name"],
                "arguments": arguments,
                "rationale": rationale,
            }
        except httpx.HTTPError:
            raise ModelError("DeepSeek 网络失败或超时") from None
        except (KeyError, IndexError, TypeError, ValueError):
            raise ModelError("DeepSeek 响应协议异常") from None
