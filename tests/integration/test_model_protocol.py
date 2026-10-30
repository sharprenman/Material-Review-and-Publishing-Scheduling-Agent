import httpx
import pytest

from material_scheduler.infrastructure.model.deepseek import DeepSeek, ModelError


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(401),
        httpx.Response(429),
        httpx.Response(200, json={"bad": "shape"}),
        httpx.Response(200, json={"choices": [{"message": {"tool_calls": []}}]}),
    ],
)
def test_failures_are_bounded_and_redacted(monkeypatch, response):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        return response

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(ModelError) as error:
        DeepSeek(key="secret-test-sentinel").choose([], [], 1)
    assert "secret-test-sentinel" not in str(error.value)
    assert len(calls) == 1


def test_network_failure_is_sanitized(monkeypatch):
    def post(*args, **kwargs):
        raise httpx.ReadTimeout("sensitive transport contents")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(ModelError, match="网络失败") as error:
        DeepSeek(key="secret-test-sentinel").choose([], [], 1)
    assert "sensitive" not in str(error.value)


def test_live_rationale_is_separated_and_redacted(monkeypatch):
    import json

    call = {
        "id": "actual-call",
        "function": {
            "name": "save_draft",
            "arguments": json.dumps(
                {
                    "time": "2026-11-01T19:00:00+08:00",
                    "rationale": "18点已占用，选择19点 sk-sentinel",
                }
            ),
        },
    }
    response = httpx.Response(
        200,
        json={
            "id": "response-id",
            "model": "deepseek-flash",
            "choices": [{"message": {"tool_calls": [call]}}],
        },
    )
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)
    action = DeepSeek(key="sk-sentinel").choose([], [], 1)
    assert action["arguments"] == {"time": "2026-11-01T19:00:00+08:00"}
    assert "选择19点" in action["rationale"] and "sk-sentinel" not in action["rationale"]


@pytest.mark.parametrize("rationale", [None, "", "   ", "超" * 181])
def test_missing_or_invalid_live_rationale_fails_safely(monkeypatch, rationale):
    import json

    call = {
        "id": "call",
        "function": {"name": "read_material", "arguments": json.dumps({"rationale": rationale})},
    }
    response = httpx.Response(200, json={"choices": [{"message": {"tool_calls": [call]}}]})
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)
    with pytest.raises(ModelError):
        DeepSeek(key="secret-test-sentinel").choose([], [], 1)


def test_failed_request_does_not_reuse_previous_response_id(monkeypatch):
    model = DeepSeek(key="secret-test-sentinel")
    model.last_metadata = {"id": "previous-response"}
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: httpx.Response(503))
    with pytest.raises(ModelError):
        model.choose([], [], 1)
    assert model.last_metadata == {}
