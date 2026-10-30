from concurrent.futures import ThreadPoolExecutor

from conftest import request

from material_scheduler.bootstrap import create_service


def test_concurrent_duplicate(settings):
    def run(_):
        s = create_service(settings)
        try:
            return s.run(request()).draft
        finally:
            s.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, range(2)))
    assert results[0] == results[1]
    s = create_service(settings)
    assert s.repo.db.execute("SELECT count(*) FROM drafts").fetchone()[0] == 1
    s.close()


def test_atomic_competing_reservations(settings):
    s = create_service(settings)
    s.close()

    def run(id):
        s = create_service(settings)
        try:
            return s.run(request(id))
        finally:
            s.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, ["one", "two"]))
    assert sum(r.draft is not None for r in results) == 1
    assert sum(r.execution == "waiting_confirmation" for r in results) == 1


def test_direct_transaction_competition(settings):
    from threading import Barrier

    from material_scheduler.domain.models import ReviewResult
    from material_scheduler.infrastructure.persistence.repository import Repository

    s = create_service(settings)
    for id in ("one", "two"):
        s.repo.register(request(id), "mock")
    s.close()
    barrier = Barrier(2)

    def save(id):
        repo = Repository(settings.runtime_dir / "business.sqlite")
        barrier.wait()
        try:
            return repo.save(
                request(id),
                request(id).requested_time.isoformat(),
                lambda: ReviewResult(status="passed"),
            )
        finally:
            repo.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(save, ["one", "two"]))
    assert sum(r.get("saved", False) for r in results) == 1
    assert sum(r.get("conflict", False) for r in results) == 1
