"""
Multi-provider LLM wrapper with automatic fallback.
Order: Groq → Cerebras → Gemini → SambaNova
"""
import json
import os
import re
import time
from typing import Optional
import user_settings

from config import PROVIDER_CHAIN, PROVIDER_CONFIG




def list_ollama_models() -> list:
    """Fetch available models from the user's local Ollama."""
    import requests
    try:
        url = user_settings.load().get("ollama_url", "http://localhost:11434")
        r = requests.get(f"{url}/api/tags", timeout=3)
        if r.status_code == 200:
            data = r.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        pass
    return []


def call_ollama(prompt: str, api_key: str, model: str) -> str:
    """Call the user's local Ollama with their chosen model."""
    import requests
    url = user_settings.load().get("ollama_url", "http://localhost:11434")

    r = requests.post(
        f"{url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_ctx": 8192},
        },
        timeout=600,
    )
    if r.status_code != 200:
        raise Exception(f"Ollama error {r.status_code}: {r.text[:200]}")
    return r.json().get("response", "")


class LLMError(Exception):
    """Raised when all providers fail."""
    pass


class ProviderError(Exception):
    """Single provider failure — triggers fallback."""
    pass


# ─────────────────────────────────────────────────────────────
# JSON extraction helper
# ─────────────────────────────────────────────────────────────
def _extract_json(text: str) -> list:
    """Extract JSON array from LLM response (handles markdown fences)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```\s*$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1:
        raise ProviderError("No JSON array found in response")
    try:
        result = json.loads(text[start:end + 1])
        if not isinstance(result, list):
            raise ProviderError("Response is not a JSON array")
        return result
    except json.JSONDecodeError as e:
        raise ProviderError(f"Invalid JSON: {e}")


# ─────────────────────────────────────────────────────────────
# Clip JSON Schema (for structured output enforcement)
# ─────────────────────────────────────────────────────────────
CLIP_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "start": {"type": "number"},
            "end": {"type": "number"},
            "title": {"type": "string"},
            "score": {"type": "integer"},
            "hook": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["start", "end", "title", "score"],
        "additionalProperties": False,
    },
}


def _openai_request(base_url: str, api_key: str, model: str,
                    prompt: str, use_json_schema: bool = True) -> str:
    """Make an OpenAI-compatible chat completion request."""
    import requests

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 4096,
    }

    # Add structured output enforcement if supported
    if use_json_schema:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "clips",
                "strict": True,
                "schema": CLIP_SCHEMA,
            },
        }
    else:
        # Best-effort JSON mode
        payload["response_format"] = {"type": "json_object"}

    r = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )

    if r.status_code == 429:
        raise ProviderError(f"Rate limited (429)")
    if r.status_code == 503:
        raise ProviderError(f"Server busy (503)")
    if r.status_code != 200:
        raise ProviderError(f"HTTP {r.status_code}: {r.text[:200]}")

    return r.json()["choices"][0]["message"]["content"]


# ─────────────────────────────────────────────────────────────
# Provider-specific call functions
# ─────────────────────────────────────────────────────────────
def call_groq(prompt: str, api_key: str, model: str) -> str:
    return _openai_request(
        "https://api.groq.com/openai/v1", api_key, model, prompt,
        use_json_schema=True,
    )


def call_cerebras(prompt: str, api_key: str, model: str) -> str:
    return _openai_request(
        "https://api.cerebras.ai/v1", api_key, model, prompt,
        use_json_schema=True,
    )


def call_sambanova(prompt: str, api_key: str, model: str) -> str:
    return _openai_request(
        "https://api.sambanova.ai/v1", api_key, model, prompt,
        use_json_schema=True,
    )


def call_gemini(prompt: str, api_key: str, model: str) -> str:
    """Gemini uses its own SDK — no OpenAI compatibility."""
    from google import genai
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
        },
    )
    return response.text


# ─────────────────────────────────────────────────────────────
# Dispatch table
# ─────────────────────────────────────────────────────────────
CALL_FNS = {
    "groq": call_groq,
    "cerebras": call_cerebras,
    "sambanova": call_sambanova,
    "gemini": call_gemini,
    "ollama": call_ollama,
}


# ─────────────────────────────────────────────────────────────
# Provider Chain — the main entry point
# ─────────────────────────────────────────────────────────────
def call_llm_with_fallback(prompt: str,
                           api_keys: Optional[dict] = None,
                           model_override: Optional[str] = None,
                           log_fn=None) -> list:
    """
    Try each provider in the chain until one succeeds.
    Returns parsed JSON list (clips array).

    For cloud providers: reads key from user_settings (AppData) first,
                         then env vars.
    For ollama: uses user's chosen model from user_settings.
    """
    if api_keys is None:
        api_keys = {}

    errors = []

    for provider_id in PROVIDER_CHAIN:
        cfg = PROVIDER_CONFIG.get(provider_id)
        if not cfg:
            continue

        # ── Determine key & model for this provider ──
        if provider_id == "ollama":
            # Local Ollama — no key needed. Use user's chosen model.
            key = "local"
            model = user_settings.get_ollama_model()
        else:
            # Cloud provider — try passed dict first, then user settings, then env
            key = (
                api_keys.get(provider_id)
                or user_settings.get_api_key(provider_id)
            )
            if not key:
                if log_fn:
                    log_fn(f"   ⏭️  {cfg['name']}: no API key — skipping")
                continue
            model = model_override if (model_override and provider_id == "groq") else cfg["models"][0]

        try:
            if log_fn:
                log_fn(f"   → Trying {cfg['name']} ({model})...")

            t0 = time.time()
            raw = CALL_FNS[provider_id](prompt, key, model)
            elapsed = time.time() - t0

            clips = _extract_json(raw)

            if log_fn:
                log_fn(f"   ✅ {cfg['name']} responded in {elapsed:.0f}s — "
                       f"{len(clips)} clips")

            return clips

        except ProviderError as e:
            if log_fn:
                log_fn(f"   ⚠️  {cfg['name']} failed: {e}")
            errors.append(f"{cfg['name']}: {e}")
            continue

        except Exception as e:
            if log_fn:
                log_fn(f"   ⚠️  {cfg['name']} error: {str(e)[:120]}")
            errors.append(f"{cfg['name']}: {str(e)[:120]}")
            continue

    # All providers failed
    error_summary = "; ".join(errors) if errors else "No providers available"
    raise LLMError(f"All providers failed: {error_summary}")


def get_providers_info() -> list:
    """For the frontend: list providers and their models."""
    result = []
    for pid in PROVIDER_CHAIN:
        cfg = PROVIDER_CONFIG.get(pid)
        if cfg:
            result.append({
                "id": pid,
                "name": cfg["name"],
                "models": cfg["models"],
                "needs_key": True,
                "has_key": bool(os.environ.get(cfg["env_key"])),
            })
    return result