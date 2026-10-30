import pytest
from conftest import request

from material_scheduler.bootstrap import create_service
from material_scheduler.domain.models import Confirmation


def test_restart_and_race(settings):
    s = create_service(settings)
    first = s.run(request(hour=18))
    p = first.proposal
    with s.repo.db:
        s.repo.db.execute("INSERT INTO slots VALUES('video','team',?,'competitor')", (p["time"],))
    s.close()
    s = create_service(settings)
    second = s.confirm("normal", Confirmation(proposal_id=p["proposal_id"], version=1, accept=True))
    assert second.execution == "waiting_confirmation"
    assert second.proposal["version"] == 2
    assert second.proposal["time"].endswith("20:00:00+08:00")
    assert second.model_calls > first.model_calls
    assert second.draft is None
    s.close()


def test_rejection(settings):
    s = create_service(settings)
    p = s.run(request(hour=18)).proposal
    result = s.confirm(
        "normal", Confirmation(proposal_id=p["proposal_id"], version=1, accept=False)
    )
    assert result.execution == "rejected" and result.draft is None
    s.close()


def test_confirm_budget_does_not_reset(settings):
    settings.max_model_calls = 5
    s = create_service(settings)
    first = s.run(request(hour=18))
    p = first.proposal
    s.close()
    s = create_service(settings)
    result = s.confirm("normal", Confirmation(proposal_id=p["proposal_id"], version=1, accept=True))
    assert result.execution == "incomplete"
    assert result.model_calls == 5 and result.draft is None
    s.close()


def test_write_before_checkpoint_replayed(settings, monkeypatch):
    s = create_service(settings)
    original = s.repo.save

    def crash_after_write(*args):
        result = original(*args)
        if result.get("saved"):
            raise KeyboardInterrupt("simulated process crash before graph checkpoint")
        return result

    monkeypatch.setattr(s.repo, "save", crash_after_write)
    import pytest

    with pytest.raises(KeyboardInterrupt):
        s.run(request())
    saved = s.repo.draft("normal")
    assert saved is not None
    # A restarted process resumes the outstanding tool, reusing the business write.
    s.close()
    s = create_service(settings)
    result = s.run(request())
    assert result.draft == saved
    assert s.repo.db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 1
    s.close()


def test_proposal_write_before_checkpoint(settings, monkeypatch):
    s = create_service(settings)
    original = s.repo.save

    def crash_after_proposal(*args):
        result = original(*args)
        if result.get("proposal"):
            raise KeyboardInterrupt("crash after proposal transaction")
        return result

    monkeypatch.setattr(s.repo, "save", crash_after_proposal)
    import pytest

    with pytest.raises(KeyboardInterrupt):
        s.run(request(hour=18))
    p = s.repo.get("normal")["proposal"]
    s.close()
    s = create_service(settings)
    result = s.confirm("normal", Confirmation(proposal_id=p["proposal_id"], version=1, accept=True))
    assert result.execution == "completed"
    assert result.draft["time"] == p["time"]
    s.close()


def test_authorization_persisted_before_resume(settings):
    s = create_service(settings)
    p = s.run(request(hour=18)).proposal
    s.repo.confirm("normal", Confirmation(proposal_id=p["proposal_id"], version=1, accept=True))
    s.close()
    s = create_service(settings)
    result = s.run(request(hour=18))
    assert result.execution == "completed"
    s.close()


@pytest.mark.parametrize("optimized", [True, False])
def test_accepted_time_survives_earlier_slot_becoming_free(settings, optimized):
    settings.context_enabled = optimized
    s = create_service(settings)
    p = s.run(request(hour=18)).proposal
    with s.repo.db:
        s.repo.db.execute(
            "DELETE FROM slots WHERE time=?", (request(hour=18).requested_time.isoformat(),)
        )
    result = s.confirm("normal", Confirmation(proposal_id=p["proposal_id"], version=1, accept=True))
    assert result.execution == "completed" and result.draft["time"] == p["time"]
    assert s.run(request(hour=18)).draft == result.draft
    s.close()
