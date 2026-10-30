import json
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path


class Trace:
    def __init__(self, path: Path, identity: dict):
        self.path = path
        self.identity = identity

    def emit(self, **event):
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            **self.identity,
            "versions": {k: version(k) for k in ("langgraph", "pydantic", "httpx")},
            **event,
        }
        encoded = json.dumps(record, ensure_ascii=False) + "\n"
        try:
            with self.path.open("a", encoding="utf-8") as output:
                output.write(encoded)
        except (OSError, UnicodeError):
            # No retry against the failed audit sink; business facts remain authoritative.
            print(
                "审计警告：Trace 写入不可用，本次审计可能不完整；业务结果以数据库为准。",
                file=sys.stderr,
            )
