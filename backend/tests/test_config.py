from __future__ import annotations

from postmortem.config import Settings, load_env_files


def test_settings_loads_dotenv_without_overriding_process_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "POSTMORTEM_DATABASE_URL=sqlite:///./from-dotenv.db",
                "POSTMORTEM_API_TOKEN=from-dotenv",
                "POSTMORTEM_DEV_BYPASS=true",
                "POSTMORTEM_CORS_ORIGINS=http://localhost:3000, http://127.0.0.1:3000",
                "POSTMORTEM_LLM_BASE_URL='https://provider.test/v1'",
                "POSTMORTEM_LLM_API_KEY=from-file # inline comment",
                "POSTMORTEM_LLM_MODEL=dotenv-model",
            ]
        ),
        encoding="utf-8",
    )
    for key in (
        "POSTMORTEM_DATABASE_URL",
        "POSTMORTEM_API_TOKEN",
        "POSTMORTEM_DEV_BYPASS",
        "POSTMORTEM_CORS_ORIGINS",
        "POSTMORTEM_LLM_BASE_URL",
        "POSTMORTEM_LLM_API_KEY",
        "POSTMORTEM_LLM_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("POSTMORTEM_LLM_MODEL", "shell-model")

    load_env_files((env_file,))
    settings = Settings.from_env()

    assert settings.database_url == "sqlite:///./from-dotenv.db"
    assert settings.api_token == "from-dotenv"
    assert settings.dev_bypass is True
    assert settings.cors_origins == ("http://localhost:3000", "http://127.0.0.1:3000")
    assert settings.llm_base_url == "https://provider.test/v1"
    assert settings.llm_api_key == "from-file"
    assert settings.llm_model == "shell-model"
