from types import SimpleNamespace

from app.llm_limits import resolve_model_token_limits


def _settings(**overrides):
    values = {
        "llm_max_output_tokens": 1024,
        "llm_e2b_context_tokens": 8192,
        "llm_e2b_max_output_tokens": 2048,
        "llm_e4b_context_tokens": 16384,
        "llm_e4b_max_output_tokens": 4096,
        "llm_31b_cloud_context_tokens": 262144,
        "llm_31b_cloud_max_output_tokens": 8192,
        "llm_unknown_context_tokens": 4096,
        "llm_context_safety_tokens": 512,
        "llm_capability_discovery_enabled": False,
        "llm_capability_timeout_seconds": 5.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_supported_models_have_distinct_output_caps():
    settings = _settings()

    assert resolve_model_token_limits(settings, "gemma4:e2b", "短提示", "", "").configured_output_tokens == 2048
    assert resolve_model_token_limits(settings, "gemma4:e4b", "短提示", "", "").configured_output_tokens == 4096
    assert resolve_model_token_limits(settings, "gemma4:31b-cloud", "短提示", "", "").configured_output_tokens == 8192


def test_effective_output_cap_reserves_prompt_and_safety_budget():
    limits = resolve_model_token_limits(
        _settings(llm_e2b_context_tokens=4096),
        "gemma4:e2b",
        "法" * 3200,
        "http://127.0.0.1:11434",
        "",
    )

    assert limits.context_tokens == 4096
    assert limits.estimated_prompt_tokens == 3200
    assert limits.effective_output_tokens == 384
