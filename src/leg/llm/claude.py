"""Minimal Claude API client (plain HTTP, no SDK). Key comes from .env or the environment."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"


def load_api_key(env_file: Path | str = ".env") -> str | None:
    """ANTHROPIC_API_KEY from the environment, else from a .env file. Empty -> None."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key and Path(env_file).exists():
        for line in Path(env_file).read_text().splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    return key or None


def complete_json(prompt: str, api_key: str, model: str | None = None, max_tokens: int = 1024) -> dict:
    """Send one user message, return the first JSON object in the reply."""
    r = requests.post(
        API_URL,
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model or os.environ.get("LEG_LLM_MODEL", DEFAULT_MODEL), "max_tokens": max_tokens,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=120,
    )
    r.raise_for_status()
    text = "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"No JSON object in LLM reply: {text[:200]!r}")
    return json.loads(m.group(0))
