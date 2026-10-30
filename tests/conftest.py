import shutil
from pathlib import Path

import pytest

from material_scheduler.bootstrap import create_service
from material_scheduler.config import Settings
from material_scheduler.domain.models import ScheduleRequest


@pytest.fixture
def settings(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(Path(__file__).resolve().parents[1] / "data", data)
    return Settings(data_dir=data, runtime_dir=tmp_path / "runtime")


@pytest.fixture
def service(settings):
    instance = create_service(settings)
    yield instance
    instance.close()


def request(id="normal", hour=17, material="M01", **kwargs):
    return ScheduleRequest(
        request_id=id,
        material_id=material,
        channel="video",
        account="team",
        requested_time=f"2026-11-01T{hour:02}:00:00+08:00",
        **kwargs,
    )
