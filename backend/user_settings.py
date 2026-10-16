"""
Per-user settings: API keys, chosen Ollama model.
Stored in %APPDATA%/AIClipStudio/settings.json on Windows.
Never committed to git, never bundled in the installer.
"""
import json
import os
from pathlib import Path


def _settings_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path.home() / ".config"
    d = base / "AIClipStudio"
    d.mkdir(parents=True, exist_ok=True)
    return d


SETTINGS_FILE = _settings_dir() / "settings.json"


DEFAULTS = {
    "api_keys": {},
    "ollama_model": "qwen2.5:7b",
    "ollama_url": "http://localhost:11434",
    "detection_provider": "groq",
}


def load() -> dict:
    if not SETTINGS_FILE.exists():
        return dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        merged = dict(DEFAULTS)
        merged.update(data)
        return merged
    except Exception:
        return dict(DEFAULTS)


def save(data: dict):
    try:
        SETTINGS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"Could not save settings: {e}")


def get_api_key(provider: str) -> str:
    """Get API key: env var first (dev), then user settings file."""
    env_key = os.environ.get(f"{provider.upper()}_API_KEY")
    if env_key:
        return env_key
    return load().get("api_keys", {}).get(provider, "")


def set_api_key(provider: str, key: str):
    data = load()
    data.setdefault("api_keys", {})[provider] = key
    save(data)


def get_ollama_model() -> str:
    return load().get("ollama_model", "qwen2.5:7b")


def set_ollama_model(model: str):
    data = load()
    data["ollama_model"] = model
    save(data)