# -*- coding: utf-8 -*-
"""Lightweight OpenAI Responses API helper for Streamlit chat."""
import os
from typing import Iterable, List, Dict, Optional
from openai import OpenAI

def _client() -> OpenAI:
    # Reads OPENAI_API_KEY from environment
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def stream_chat(messages: List[Dict[str, str]], system_prompt: Optional[str] = None, model: str = "gpt-4o-mini") -> Iterable[str]:
    """Yield assistant text tokens using the Responses API streaming interface.
    `messages` must be a list like: [{"role": "user"|"assistant", "content": "..."}, ...]
    """
    client = _client()
    # Build Responses API 'input' events
    events = []
    if system_prompt:
        events.append({"role": "system", "content": [{"type": "input_text", "text": system_prompt}]})
    for m in messages:
        role = m.get("role", "user")
        text = m.get("content", "")
        events.append({"role": role, "content": [{"type": "input_text", "text": text}]})

    # Stream tokens
    with client.responses.stream(model=model, input=events) as stream:
        for event in stream:
            if event.type == "response.output_text.delta":
                yield event.delta  # a chunk of text
            # You can handle other event types here if needed (e.g., tool calls)
        _ = stream.get_final_response()  # ensure the stream closes cleanly
