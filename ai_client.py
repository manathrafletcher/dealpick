"""
MFA DealPick - AI client (Groq, free tier)
Used only to tidy the wording of a notice draft. Every notice still goes to an advocate.

Carried over from the original Dratido client: model discovery (cached), failover to the
next model on rate limits/errors, small per-call token budgets.
"""

import os
import time
import threading

import requests
from requests.adapters import HTTPAdapter

GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")

_PREFERRED = ["llama-3.3-70b-versatile", "openai/gpt-oss-120b",
              "llama-3.1-8b-instant", "openai/gpt-oss-20b"]
_EXCLUDED = ("whisper", "guard", "safeguard", "compound", "tts", "orpheus",
             "playai", "embed", "moderation")
MAX_MODELS_TRIED = 4
RATE_LIMIT_MAX_WAIT = 12

_HTTP = requests.Session()
_HTTP.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=8))

_CACHE = {"models": None, "expires": 0.0}
_LOCK = threading.Lock()


class _Skip(Exception):
    pass


class _RateLimited(Exception):
    def __init__(self, wait):
        super().__init__(f"rate limited, retry in {wait}s")
        self.wait = wait


def ai_available() -> bool:
    return bool(os.environ.get("GROQ_API_KEY", "").strip())


def _models(api_key):
    now = time.time()
    with _LOCK:
        if _CACHE["models"] is None or now > _CACHE["expires"]:
            ids, ok = [], False
            try:
                r = _HTTP.get(f"{GROQ_BASE_URL}/models",
                              headers={"Authorization": f"Bearer {api_key}"}, timeout=(4, 6))
                if r.status_code == 200:
                    ids = [i["id"] for i in r.json().get("data", [])
                           if isinstance(i, dict) and i.get("id") and i.get("active", True)]
                    ok = True
            except Exception as e:                      # discovery is best-effort
                print(f"[AI] model discovery failed: {e}")
            if ids:
                sel = [m for m in _PREFERRED if m in ids]
                sel += [m for m in ids if m not in sel and not any(x in m.lower() for x in _EXCLUDED)]
            else:
                sel = list(_PREFERRED)
            override = os.environ.get("GROQ_MODEL", "").strip()
            if override:
                sel = [override] + [m for m in sel if m != override]
            _CACHE["models"] = list(dict.fromkeys(sel))
            _CACHE["expires"] = now + (3600 if ok else 30)
        return list(_CACHE["models"])[:MAX_MODELS_TRIED]


def _once(api_key, model, messages, temperature, max_tokens):
    payload = {"model": model, "messages": messages, "temperature": temperature,
               "max_completion_tokens": max_tokens}
    if model.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    try:
        r = _HTTP.post(f"{GROQ_BASE_URL}/chat/completions",
                       headers={"Authorization": f"Bearer {api_key}",
                                "Content-Type": "application/json"},
                       json=payload, timeout=(5, 60))
    except requests.exceptions.RequestException as e:
        raise _Skip(f"request error on {model}: {e}")
    if r.status_code == 429:
        try:
            wait = max(0.5, min(float(r.headers.get("retry-after", "")), 60.0))
        except (TypeError, ValueError):
            wait = 5.0
        raise _RateLimited(wait)
    if r.status_code != 200:
        raise _Skip(f"HTTP {r.status_code} on {model}: {r.text[:160]}")
    try:
        choice = r.json()["choices"][0]
        text = choice["message"]["content"] or ""
    except Exception as e:
        raise _Skip(f"bad response from {model}: {e}")
    if not text.strip():
        raise _Skip(f"empty content from {model}")
    return text, choice.get("finish_reason")


def ai_generate(prompt: str, system: str = "", temperature: float = 0.2,
                max_tokens: int = 2800) -> str:
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("AI is not set up. Add GROQ_API_KEY in the server settings.")
    messages = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": "user", "content": prompt}]
    models = _models(api_key)
    last = None
    for rnd in range(2):
        wait = None
        for m in models:
            try:
                text, finish = _once(api_key, m, messages, temperature, max_tokens)
                if finish == "length":
                    raise _Skip(f"{m} ran out of tokens before finishing")
                return text.strip()
            except _RateLimited as e:
                last = f"rate limited on {m}"
                wait = e.wait if wait is None else min(wait, e.wait)
            except _Skip as e:
                last = str(e)
        if wait is None or rnd == 1:
            break
        time.sleep(min(wait, RATE_LIMIT_MAX_WAIT))
    raise RuntimeError(f"The AI service could not finish this request ({last}).")
