"""One OpenAI-compatible client for every provider (NVIDIA Brev via vLLM, NVIDIA Build, ...).
Switching provider is a config change. If the primary fails, the fallback is tried."""
import base64
import json
import re
import time

from openai import OpenAI

from . import config


class LLMError(Exception):
    pass


def _client(p: dict) -> OpenAI:
    return OpenAI(base_url=p["base_url"], api_key=p["api_key"] or "missing-key",
                  timeout=config.LLM_TIMEOUT_S, max_retries=0)


def _messages(prompt: str, image_bytes: bytes | None, mime: str, mode: str) -> list:
    if image_bytes is None:
        return [{"role": "user", "content": prompt}]
    b64 = base64.b64encode(image_bytes).decode()
    if mode == "inline_img":
        return [{"role": "user", "content": f'{prompt} <img src="data:{mime};base64,{b64}" />'}]
    return [{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]}]


def _first_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("model returned no JSON object")
    return json.loads(text[start:end + 1])


def complete_json(prompt: str, image_bytes: bytes | None = None, mime: str = "image/png") -> dict:
    """Returns {"data": <parsed JSON>, "provider": label, "model": id, "ms": latency}.
    Raises LLMError if every provider fails."""
    errors = []
    for p in [config.PRIMARY, config.FALLBACK]:
        if not p:
            continue
        for _attempt in range(2):  # one retry for malformed JSON
            t0 = time.monotonic()
            try:
                resp = _client(p).chat.completions.create(
                    model=p["model"],
                    messages=_messages(prompt, image_bytes, mime, p["image_mode"]),
                    temperature=0,
                    max_tokens=600,
                )
                data = _first_json(resp.choices[0].message.content or "")
                return {"data": data, "provider": p["label"], "model": p["model"],
                        "ms": int((time.monotonic() - t0) * 1000)}
            except (json.JSONDecodeError, LLMError) as e:
                errors.append(f"{p['label']}: bad JSON ({e})")
                continue
            except Exception as e:  # network, auth, rate limit: go to the next provider
                errors.append(f"{p['label']}: {type(e).__name__}")
                break
    raise LLMError("; ".join(errors) or "no provider configured")
