"""Configuration — works both as Python script and as packaged .exe."""
import os
import sys
from pathlib import Path


def _get_base_dir():
    """Return the correct base folder whether running normally or as .exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


BASE_DIR = _get_base_dir()
BACKEND_DIR = BASE_DIR / "backend"
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "output"
TEMP_DIR = DATA_DIR / "temp"
UPLOADS_DIR = DATA_DIR / "uploads"
PINNED_DIR = OUTPUT_DIR / "_pinned"
FRONTEND_DIR = BASE_DIR / "frontend"

for d in [OUTPUT_DIR, TEMP_DIR, UPLOADS_DIR, PINNED_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Clip rules
MIN_CLIP_SECONDS = 30
MAX_CLIP_SECONDS = 60
DEFAULT_CLIPS = 10

# Whisper
WHISPER_MODEL = "tiny"
WHISPER_LANGUAGE = "en"
WHISPER_BEAM_SIZE = 1
WHISPER_CPU_THREADS = 8

# Provider chain
PROVIDER_CHAIN = ["groq", "cerebras", "gemini", "ollama"]

PROVIDER_CONFIG = {
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        "env_key": "GROQ_API_KEY",
        "needs_key": True,
    },
    "cerebras": {
        "name": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "models": ["llama3.3-70b", "llama3.1-8b"],
        "env_key": "CEREBRAS_API_KEY",
        "needs_key": True,
    },
    "gemini": {
        "name": "Google Gemini",
        "base_url": None,
        "models": ["gemini-flash-latest", "gemini-2.0-flash"],
        "env_key": "GEMINI_API_KEY",
        "needs_key": True,
    },
    "ollama": {
        "name": "Ollama (local)",
        "base_url": "http://localhost:11434",
        "models": [],  # filled dynamically from /api/tags
        "env_key": None,
        "needs_key": False,
    },
}

FUSION_WEIGHTS = {"llm": 0.45, "audio": 0.30, "heuristic": 0.25}

# Caption burning (off by default — user toggles)
BURN_CAPTIONS_DEFAULT = False
CAPTION_STYLE = {
    "font_name": "Arial Black",
    "font_size": 72,
    "primary_color": "&H00FFFFFF",
    "highlight_color": "&H0000FFFF",
    "outline_color": "&H00000000",
    "outline_width": 7,
    "margin_v": 150,
    "words_per_line": 3,
    "play_res_x": 1080,
    "play_res_y": 1920,
}