from __future__ import annotations

from typing import Any

import requests

from .config import Settings


def generate_summary(settings: Settings, prompt: str) -> tuple[str, str]:
    if not settings.llm_enabled:
        return _fallback_summary(prompt), "local-fallback"

    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    payload: dict[str, Any] = {
        "model": settings.llm_model,
        "input": prompt,
    }

    response = requests.post(
        settings.llm_api_url,
        json=payload,
        headers=headers,
        timeout=settings.llm_timeout_seconds,
    )
    response.raise_for_status()
    data = response.json()

    text = _extract_text(data)
    if not text:
        text = _fallback_summary(prompt)
    return text, settings.llm_model


def _extract_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()

    # OpenAI-like response fallback
    output = data.get("output")
    if isinstance(output, list):
        chunks: list[str] = []
        for item in output:
            content = item.get("content") if isinstance(item, dict) else None
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    txt = part.get("text")
                    if isinstance(txt, str):
                        chunks.append(txt)
        return "\n".join(chunks).strip()

    if isinstance(data.get("choices"), list) and data["choices"]:
        message = data["choices"][0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()

    return ""


def _fallback_summary(prompt: str) -> str:
    preview = prompt.strip().splitlines()[:12]
    return (
        "LLM is not configured. Local deterministic summary generated from telemetry snapshot.\n"
        + "\n".join(preview)
    )
