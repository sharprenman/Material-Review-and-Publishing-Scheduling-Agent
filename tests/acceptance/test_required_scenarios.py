import json

import pytest
from conftest import request

from material_scheduler.domain.models import Confirmation
from material_scheduler.infrastructure.persistence.repository import BusinessError


def test_normal_and_duplicate(service):
    first = service.run(request())
    assert first.execution == "completed"
    assert first.save_status == "saved"
    assert first.draft == service.repo.draft("normal")
    assert service.run(request()).draft == first.draft
    assert service.repo.db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 1
    with pytest.raises(BusinessError, match="不同业务内容"):
        service.run(request(hour=16))
    assert service.status("normal").draft == first.draft


@pytest.mark.parametrize(
    ("material", "status"), [("M02", "missing"), ("M03", "blocked"), ("unknown", "missing")]
)
def test_review_blocks_save(service, material, status):
    result = service.run(request(material=material))
    assert result.execution == "blocked"
    assert result.review["status"] == status
    assert result.draft is None
    assert result.review["missing"] or result.review["risks"]


def test_conflict_confirmation(service):
    result = service.run(request(hour=18))
    assert result.execution == "waiting_confirmation"
    assert result.requested_time.endswith("18:00:00+08:00")
    assert result.proposal["time"].endswith("19:00:00+08:00")
    assert result.draft is None
    p = result.proposal
    with pytest.raises(BusinessError):
        service.confirm(
            "normal", Confirmation(proposal_id=p["proposal_id"], version=99, accept=True)
        )
    result = service.confirm(
        "normal", Confirmation(proposal_id=p["proposal_id"], version=p["version"], accept=True)
    )
    assert result.draft["time"] == p["time"]
    with pytest.raises(BusinessError):
        service.confirm(
            "normal", Confirmation(proposal_id=p["proposal_id"], version=p["version"], accept=True)
        )


def test_changed_occupancy_is_observed(service):
    first = service.run(request(hour=18))
    with service.repo.db:
        service.repo.db.execute(
            "INSERT INTO slots VALUES('video','team',?, 'other')", (first.proposal["time"],)
        )
    second = service.run(request("changed", hour=18))
    assert second.proposal["time"].endswith("20:00:00+08:00")
    assert second.proposal["time"] != first.proposal["time"]


def test_save_failure_rolls_back(service):
    service.repo.db.executescript("""
      CREATE TRIGGER fail_draft BEFORE INSERT ON drafts
      BEGIN SELECT RAISE(ABORT,'injected disk write failure'); END;
    """)
    result = service.run(request())
    assert result.execution == "failed" and result.save_status == "failed"
    assert service.repo.draft("normal") is None
    assert (
        service.repo.db.execute("SELECT count(*) FROM slots WHERE owner='normal'").fetchone()[0]
        == 0
    )


def test_account_isolation(service):
    r = request(hour=18).model_copy(update={"account": "other"})
    assert service.run(r).execution == "completed"


def test_latest_rules_rechecked(service, settings):
    from material_scheduler.application.tools import Tools

    service.repo.register(request(), "mock")
    tools = Tools(service.repo, service.catalog)
    obs = {}
    for name in ("read_material", "check_rules", "query_slots"):
        obs[name] = tools.execute("normal", name, {}, obs)
    materials = json.loads((settings.data_dir / "materials.json").read_text())
    materials[0]["rights"] = False
    (settings.data_dir / "materials.json").write_text(json.dumps(materials))
    outcome = tools.execute(
        "normal", "save_draft", {"time": request().requested_time.isoformat()}, obs
    )
    assert outcome["review"]["status"] == "blocked"
    assert service.repo.draft("normal") is None


def test_no_later_slots(service):
    from datetime import datetime

    with service.repo.db:
        for hour in range(19, 24):
            service.repo.db.execute(
                "INSERT INTO slots VALUES('video','team',?,'full')",
                (datetime.fromisoformat(f"2026-11-01T{hour}:00:00+08:00").isoformat(),),
            )
    result = service.run(request(hour=18))
    assert result.execution == "incomplete" and result.draft is None
    assert result.error == "no_slots"


def test_changed_risk_after_confirmation(service, settings):
    result = service.run(request(hour=18))
    materials = json.loads((settings.data_dir / "materials.json").read_text())
    materials[0]["rights"] = False
    (settings.data_dir / "materials.json").write_text(json.dumps(materials))
    p = result.proposal
    result = service.confirm(
        "normal", Confirmation(proposal_id=p["proposal_id"], version=1, accept=True)
    )
    assert result.execution == "blocked" and result.draft is None
    assert result.review["risks"][0]["rule_id"] == "RIGHTS"
