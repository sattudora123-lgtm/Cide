"""Provider calls. URLs are fixed constants so a user cannot redirect the server.

Apinex and Bytez are the supported providers. OpenAI, Anthropic, and Gemini
remain available when a user stores a key for them.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

APINEX_URL = "https://api.apinex.bond/v1/chat/completions"
BYTEZ_URL = "https://api.bytez.com/models/v2/"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/"
logger = logging.getLogger("cide.providers")


class ProviderTimeout(Exception):
    pass


class ProviderError(Exception):
    pass


class ProviderRateLimited(ProviderError):
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
    if ".." in model or model.startswith("/") or "\\" in model:
        raise ProviderError
    url, headers, payload = _request(provider, model, api_key, instruction, max_tokens)
    try:
        response = await http.post(url, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        raise ProviderTimeout from exc
    except httpx.HTTPError as exc:
        raise ProviderError from exc
    if response.status_code == 429:
        logger.warning("provider rate limited provider=%s", provider)
        raise ProviderRateLimited
    if response.status_code != 200:
        logger.warning("provider request failed provider=%s status=%s", provider, response.status_code)
        raise ProviderError
    try:
        text = _extract(provider, response.json())
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError from exc
    if not text.strip():
        raise ProviderError
    return text


def _request(provider: str, model: str, api_key: str, instruction: str, max_tokens: int) -> tuple[str, dict, dict]:
    messages = [{"role": "user", "content": instruction}]
    if provider == "apinex":
        return (
            APINEX_URL,
            {"Authorization": f"Bearer {api_key}"},
            {"model": model, "messages": messages, "max_tokens": max_tokens},
        )
    if provider == "bytez":
        safe_model = quote(model, safe="/")
        return (
            f"{BYTEZ_URL}{safe_model}",
            {"Authorization": api_key},
            {
                "messages": messages,
                "stream": False,
                "params": {"max_new_tokens": max_tokens},
            },
        )
    if provider == "openai":
        return (
            OPENAI_URL,
            {"Authorization": f"Bearer {api_key}"},
            {"model": model, "messages": messages, "max_tokens": max_tokens},
        )
    if provider == "anthropic":
        return (
            ANTHROPIC_URL,
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            {"model": model, "max_tokens": max_tokens, "messages": messages},
        )
    if provider == "gemini":
        safe_model = quote(model, safe="")
        return (
            f"{GEMINI_URL}{safe_model}:generateContent",
            {"x-goog-api-key": api_key},
            {"contents": [{"parts": [{"text": instruction}]}]},
        )
    raise ProviderError


def _extract(provider: str, data: dict) -> str:
    if provider in {"apinex", "openai"}:
        return _openai_text(data)
    if provider == "anthropic":
        parts = [
            block["text"]
            for block in data["content"]
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        ]
        return "".join(parts)
    if provider == "gemini":
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part["text"] for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str))
    if provider == "bytez":
        return _bytez_text(data)
    raise ProviderError


def _openai_text(data: dict) -> str:
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(item["text"] for item in content if isinstance(item, dict) and isinstance(item.get("text"), str))
    raise ProviderError


def _bytez_text(data: dict) -> str:
    if data.get("error"):
        raise ProviderError
    output = data.get("output")
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for key in ("content", "text", "generated_text"):
            if isinstance(output.get(key), str):
                return output[key]
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("content"), str):
                    parts.append(item["content"])
                elif isinstance(item.get("text"), str):
                    parts.append(item["text"])
        return "".join(parts)
    raise ProviderError
