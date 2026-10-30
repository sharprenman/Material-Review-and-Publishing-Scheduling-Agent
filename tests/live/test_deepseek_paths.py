"""Opt-in paid integration test. Default pytest never sends a network request."""

import os

import pytest
from conftest import request

from material_scheduler.bootstrap import create_service
from material_scheduler.infrastructure.model.deepseek import DeepSeek


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="显式设置 RUN_LIVE=1 才调用真实API")
def test_live_normal(settings):
    settings.mode = "live"
    settings.max_model_calls = 6
    s = create_service(settings, DeepSeek())
    try:
        result = s.run(request())
        assert result.execution == "completed"
        assert result.draft == s.repo.draft("normal")
    finally:
        s.close()
