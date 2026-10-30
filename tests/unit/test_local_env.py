from material_scheduler.infrastructure.model.deepseek import DeepSeek


def test_loads_local_env_without_overriding_shell(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    (tmp_path / ".env").write_text(
        "DEEPSEEK_API_KEY=file-test-key\nDEEPSEEK_MODEL=file-test-model\n"
    )
    model = DeepSeek()
    assert model.key == "file-test-key"
    assert model.name == "file-test-model"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "shell-test-key")
    assert DeepSeek().key == "shell-test-key"
    assert DeepSeek(key="explicit-test-key").key == "explicit-test-key"
