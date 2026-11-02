"""Provider calls. URLs are fixed constants so a user cannot redirect the server."""

from __future__ import annotations

import logging

import httpx

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
logger = logging.getLogger("cide.providers")


class ProviderTimeout(Exception):
    pass


class ProviderError(Exception):
    pass


async def complete_chat(
    http: httpx.AsyncClient,
    *,
    provider: str,
    model: str,
    api_key: str,
    instruction: str,
    max_tokens: int,
) -> str:
    if provider == "openai":
        url = OPENAI_URL
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": instruction}],
            "max_tokens": max_tokens,
        }
    elif provider == "anthropic":
        url = ANTHROPIC_URL
        headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": instruction}],
        }
    else:
        raise ProviderError
    try:
        response = await http.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ProviderTimeout from exc
    except httpx.HTTPError as exc:
        raise ProviderError from exc
    if response.status_code != 200:
        logger.warning("provider request failed provider=%s status=%s", provider, response.status_code)
        raise ProviderError
    try:
        text = _extract(provider, response.json())
    except Exception as exc:
        raise ProviderError from exc
    if not text.strip():
        raise ProviderError
    return text


def _extract(provider: str, data: dict) -> str:
    if provider == "openai":
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [item["text"] for item in content if isinstance(item, dict) and isinstance(item.get("text"), str)]
            return "".join(parts)
        raise KeyError
    parts = [
        block["text"]
        for block in data["content"]
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    ]
    return "".join(parts)
