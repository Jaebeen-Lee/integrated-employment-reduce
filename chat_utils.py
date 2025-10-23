# -*- coding: utf-8 -*-
"""OpenAI Responses API helper for Streamlit chat (streaming)."""
import os
from typing import Iterable, List, Dict, Optional
from openai import OpenAI

def _client() -> OpenAI:
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def stream_chat(messages: List[Dict[str, str]], system_prompt: Optional[str] = None, model: str = "gpt-4o-mini") -> Iterable[str]:
    """Yield assistant text tokens using Responses API streaming.
    `messages` is a list like: [{"role": "user"|"assistant", "content": "..."}, ...]
    """
    client = _client()

    events = []
    # system -> input_text
    if system_prompt:
        events.append({
            "role": "system",
            "content": [{"type": "input_text", "text": system_prompt}],
        })
    # history
    for m in messages:
        role = m.get("role", "user")
        text = m.get("content", "")
        # IMPORTANT: assistant messages must be 'output_text'
        ctype = "output_text" if role == "assistant" else "input_text"
        events.append({
            "role": role,
            "content": [{"type": ctype, "text": text}],
        })

    # Stream
    with client.responses.stream(model=model, input=events) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta
        _ = stream.get_final_response()
