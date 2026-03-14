import model_selection


def test_load_selection_falls_back_to_default_for_missing_file(monkeypatch, tmp_path):
    missing_path = tmp_path / "missing-model-settings.json"
    monkeypatch.setenv("MULTI_AGENT_SETTINGS_PATH", str(missing_path))

    selection = model_selection._load_selection("scheduler")

    assert selection == dict(model_selection.DEFAULT_SELECTION)


def test_apply_model_selection_uses_override_and_env_api_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-test-key")

    provider, model, base_url, api_key = model_selection.apply_model_selection(
        override={
            "provider": "groq",
            "model": "qwen/qwen3-32b",
            "base_url": "https://api.groq.com/openai/v1/",
        }
    )

    assert provider == "groq"
    assert model == "qwen/qwen3-32b"
    assert base_url == "https://api.groq.com/openai/v1"
    assert api_key == "groq-test-key"


def test_normalise_base_url_sanitizes_cross_provider_values():
    gemini_meta = model_selection.PROVIDER_DEFAULTS["gemini"]
    groq_meta = model_selection.PROVIDER_DEFAULTS["groq"]
    openai_meta = model_selection.PROVIDER_DEFAULTS["openai"]

    assert (
        model_selection._normalise_base_url(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta",
            gemini_meta,
        )
        == "https://generativelanguage.googleapis.com/v1beta/openai"
    )
    assert (
        model_selection._normalise_base_url(
            "groq",
            "https://example.com/v1",
            groq_meta,
        )
        == "https://api.groq.com/openai/v1"
    )
    assert (
        model_selection._normalise_base_url(
            "openai",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            openai_meta,
        )
        is None
    )


def test_provider_supports_vision():
    assert model_selection.provider_supports_vision("openai") is True
    assert model_selection.provider_supports_vision("claude") is True
    assert model_selection.provider_supports_vision("gemini") is True
    assert model_selection.provider_supports_vision("groq") is False
