# -*- coding: utf-8 -*-
"""OpenAI Responses API helper for Streamlit chat (streaming)."""
import os
from typing import Iterable, List, Dict, Optional
from openai import OpenAI

def _client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    return OpenAI(api_key=key)

def _ctype_for_role(role: str) -> str:
    r = (role or "user").lower()
    # Only assistant outputs are 'output_text'; all inputs use 'input_text'
    return "output_text" if r in ("assistant", "model") else "input_text"

def stream_chat(messages: List[Dict[str, str]], system_prompt: Optional[str] = None, model: str = "gpt-4o-mini") -> Iterable[str]:
    """Yield assistant text tokens using Responses API streaming.
    `messages` is a list like: [{"role": "user"|"assistant", "content": "..."}, ...]
    """
    client = _client()

    events = []
    # system prompt as input_text
    if system_prompt:
        events.append({
            "role": "system",
            "content": [{"type": "input_text", "text": system_prompt}],
        })
    for m in messages:
        role = m.get("role", "user")
        text = m.get("content", "")
        events.append({
            "role": role,
            "content": [{"type": _ctype_for_role(role), "text": text}],
        })

    with client.responses.stream(model=model, input=events) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta
        _ = stream.get_final_response()
