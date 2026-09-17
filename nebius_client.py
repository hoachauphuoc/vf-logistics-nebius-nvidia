"""
Nebius Token Factory client.

Token Factory exposes an OpenAI-compatible chat completions API, so this is a
thin wrapper around `openai.AsyncOpenAI` rather than a bespoke SDK. Two helpers
cover everything the four agents need:

  * complete_json         - text-only prompt, JSON-mode response (fraud,
                             compliance, investigation agents)
  * complete_vision_json  - a document image/PDF page plus a text prompt,
                             JSON-mode response (document intake agent)

Both return (text, input_tokens, output_tokens) so the caller can plug the
result straight into agents/_common.py's parse_model_json()/envelope().
"""

from __future__ import annotations

import base64
import os

from openai import AsyncOpenAI

NEBIUS_BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")
NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "")

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """Lazily build the client so import doesn't fail before NEBIUS_API_KEY is set."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(base_url=NEBIUS_BASE_URL, api_key=NEBIUS_API_KEY)
    return _client


def _usage(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0
    input_t = getattr(usage, "prompt_tokens", 0) or 0
    output_t = getattr(usage, "completion_tokens", 0) or 0
    return input_t, output_t


async def complete_json(
    *, model: str, system_prompt: str, user_text: str, temperature: float = 0.1
) -> tuple[str, int, int]:
    """
    One text-only, JSON-mode chat completion.

    Returns (raw_text, input_tokens, output_tokens). Raises on transport/API
    errors - callers already run inside a Timer/try structure in each agent.
    """
    client = get_client()
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content or ""
    input_tokens, output_tokens = _usage(response)
    return text, input_tokens, output_tokens


async def complete_vision_json(
    *,
    model: str,
    system_prompt: str,
    document_bytes: bytes,
    mime_type: str,
    user_text: str,
    temperature: float = 0.0,
) -> tuple[str, int, int]:
    """
    One multimodal (image/PDF-page + text), JSON-mode chat completion.

    Images/documents are sent as base64 data URLs, the standard OpenAI-compatible
    multimodal message shape that vision models on Token Factory accept.
    """
    client = get_client()
    b64 = base64.b64encode(document_bytes).decode("ascii")
    data_url = f"data:{mime_type};base64,{b64}"

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": user_text},
                ],
            },
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    text = response.choices[0].message.content or ""
    input_tokens, output_tokens = _usage(response)
    return text, input_tokens, output_tokens
