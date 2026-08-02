"""AI summaries for reels — built from the caption/metadata we already store.

Deliberately makes **zero Instagram calls**: it summarizes the caption, owner,
collection and tags already in the DB, so it can never irritate the account.
The only network call is to the AI provider (Anthropic), keyed off an env var;
without a key the feature is inert and callers get a clear message.

Uses plain ``requests`` (already a dependency) rather than an SDK, to stay
wheel-free on the very new Python the owner runs.
"""
from __future__ import annotations

import requests

from . import config

_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_TIMEOUT = 30

_SYSTEM = (
    "You write one-sentence summaries of short-form videos (Instagram reels) "
    "from their caption and metadata. Be concrete and neutral. Say what the reel "
    "is about or teaches, not that it's a reel. No hashtags, no emoji, no "
    "preamble like 'This reel'. Max 25 words. If there's too little to go on, "
    "reply with exactly: (no summary)."
)


class AIUnavailable(RuntimeError):
    """Raised when no API key is configured — the feature is simply off."""


def available() -> bool:
    return bool(config.AI_KEY)


def build_prompt(caption: str, owner: str, collection: str, tags: list[str]) -> str:
    parts = []
    if owner:
        parts.append(f"Posted by: @{owner}")
    if collection:
        parts.append(f"Saved in collection: {collection}")
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    parts.append("Caption:\n" + (caption.strip() or "(no caption)"))
    return "\n".join(parts)


def summarize(caption: str, owner: str = "", collection: str = "",
              tags: list[str] | None = None) -> str:
    """Return a one-line summary, or '' when there's nothing worth summarizing.

    Raises AIUnavailable if no key is set, or RuntimeError on an API error so the
    caller (a paced background job) can treat it as a back-off signal.
    """
    if not config.AI_KEY:
        raise AIUnavailable(
            "No AI key configured. Set REELER_AI_KEY (or ANTHROPIC_API_KEY) to "
            "enable summaries."
        )
    # Nothing to summarize from — don't spend a call.
    if not (caption or "").strip() and not (collection or "").strip():
        return ""

    prompt = build_prompt(caption or "", owner or "", collection or "", tags or [])
    resp = requests.post(
        _API_URL,
        headers={
            "x-api-key": config.AI_KEY,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json={
            "model": config.AI_MODEL,
            "max_tokens": 120,
            "system": _SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=_TIMEOUT,
    )
    if resp.status_code == 429 or resp.status_code >= 500:
        raise RuntimeError(f"AI rate-limited/unavailable (HTTP {resp.status_code})")
    if resp.status_code != 200:
        raise RuntimeError(f"AI request failed (HTTP {resp.status_code}): "
                           f"{resp.text[:200]}")
    try:
        data = resp.json()
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        ).strip()
    except (ValueError, AttributeError):
        raise RuntimeError("AI returned an unexpected response shape")
    if not text or text.lower() == "(no summary)":
        return ""
    return text
