import hashlib
import json
from pathlib import Path

from pydantic import TypeAdapter

from material_scheduler.domain.models import Material, Rule, ScheduleRequest
from material_scheduler.domain.policies import review


class Catalog:
    def __init__(self, directory: Path):
        self.directory = directory
        self.materials()  # Fail at startup rather than silently treating invalid files as missing.
        self.rules()

    def materials(self) -> dict[str, Material]:
        records = TypeAdapter(list[Material]).validate_json(
            (self.directory / "materials.json").read_text()
        )
        if len({r.material_id for r in records}) != len(records):
            raise ValueError("重复素材 ID")
        return {r.material_id: r for r in records}

    def rules(self) -> list[Rule]:
        return TypeAdapter(list[Rule]).validate_json((self.directory / "rules.json").read_text())

    def evaluate(self, material_id: str):
        return review(self.materials().get(material_id), self.rules())

    def schedules(self) -> list[dict]:
        rows = json.loads((self.directory / "schedules.json").read_text())
        return [
            {
                "channel": r["channel"],
                "account": r["account"],
                "time": ScheduleRequest(
                    request_id="seed",
                    material_id="seed",
                    channel=r["channel"],
                    account=r["account"],
                    requested_time=r["time"],
                ).requested_time.isoformat(),
            }
            for r in rows
        ]

    def rules_version(self) -> str:
        body = {"builtin_policy_version": 1, "rules": [r.model_dump() for r in self.rules()]}
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    def material_version(self, material_id: str) -> str:
        material = self.materials().get(material_id)
        body = material.model_dump_json() if material else "missing"
        return hashlib.sha256(body.encode()).hexdigest()
