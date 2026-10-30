import pytest
from conftest import request
from pydantic import ValidationError

from material_scheduler.application.tools import Tools


def test_forged_confirmation_and_unknown_tool(service):
    service.repo.register(request(hour=18), "mock")
    tools = Tools(service.repo, service.catalog)
    obs = {}
    for name in ("read_material", "check_rules", "query_slots"):
        obs[name] = tools.execute("normal", name, {}, obs)
    with pytest.raises(ValidationError):
        tools.execute(
            "normal", "save_draft", {"time": "2026-11-01T19:00:00+08:00", "confirmed": True}, obs
        )
    with pytest.raises(ValueError):
        tools.execute("normal", "publish", {}, obs)
    assert service.repo.draft("normal") is None


def test_save_without_observation(service):
    service.repo.register(request(), "mock")
    outcome = Tools(service.repo, service.catalog).execute(
        "normal", "save_draft", {"time": request().requested_time.isoformat()}, {}
    )
    assert "error" in outcome
    assert service.repo.draft("normal") is None


def test_time_validation():
    from material_scheduler.domain.models import ScheduleRequest

    base = request().model_dump()
    with pytest.raises(ValidationError):
        ScheduleRequest.model_validate(base | {"requested_time": "2026-11-01T17:30:00+08:00"})
    assert (
        ScheduleRequest.model_validate(
            base | {"requested_time": "2026-11-01T09:00:00Z"}
        ).requested_time.hour
        == 17
    )


def test_finish_cannot_skip_review(service):
    service.repo.register(request(material="M02"), "mock")
    tools = Tools(service.repo, service.catalog)
    read = tools.execute("normal", "read_material", {}, {})
    early = tools.execute("normal", "finish", {"reason": "missing"}, {"read_material": read})
    assert "error" in early and "reason" not in early
    audit = tools.execute("normal", "check_rules", {}, {"read_material": read})
    assert audit["status"] == "missing"
    assert tools.execute("normal", "finish", {"reason": "missing"}, {"check_rules": audit}) == {
        "reason": "missing"
    }


def test_later_candidate_is_recoverable(service):
    service.repo.register(request(), "mock")
    tools = Tools(service.repo, service.catalog)
    obs = {}
    for name in ("read_material", "check_rules", "query_slots"):
        obs[name] = tools.execute("normal", name, {}, obs)
    bad = tools.execute(
        "normal", "save_draft", {"time": obs["query_slots"]["slots"][2]["time"]}, obs
    )
    assert "error" in bad
    good = tools.execute(
        "normal", "save_draft", {"time": request().requested_time.isoformat()}, obs
    )
    assert good["saved"]


@pytest.mark.parametrize("reason", ["blocked", "missing", "no_slots"])
def test_finish_reason_requires_matching_evidence(service, reason):
    service.repo.register(request(), "mock")
    tools = Tools(service.repo, service.catalog)
    obs = {}
    for name in ("read_material", "check_rules", "query_slots"):
        obs[name] = tools.execute("normal", name, {}, obs)
    assert "error" in tools.execute("normal", "finish", {"reason": reason}, obs)


def test_finish_no_slots_without_query(service):
    service.repo.register(request(), "mock")
    tools = Tools(service.repo, service.catalog)
    obs = {"check_rules": {"status": "passed"}}
    service.repo.update("normal", review=obs["check_rules"])
    assert "error" in tools.execute("normal", "finish", {"reason": "no_slots"}, obs)


def test_changed_candidates_require_requery(service):
    service.repo.register(request(), "mock")
    tools = Tools(service.repo, service.catalog)
    obs = {}
    for name in ("read_material", "check_rules", "query_slots"):
        obs[name] = tools.execute("normal", name, {}, obs)
    # A formerly occupied, earlier slot becomes free after the snapshot.
    with service.repo.db:
        service.repo.db.execute("DELETE FROM slots WHERE time=?", ("2026-11-01T18:00:00+08:00",))
    result = tools.execute(
        "normal", "save_draft", {"time": request().requested_time.isoformat()}, obs
    )
    assert result["conflict"] and "query_slots" in result["error"]
    assert service.repo.draft("normal") is None


def test_incomplete_is_explicit_bounded_exit(service):
    service.repo.register(request(), "mock")
    assert Tools(service.repo, service.catalog).execute(
        "normal", "finish", {"reason": "incomplete"}, {}
    ) == {"reason": "incomplete"}
