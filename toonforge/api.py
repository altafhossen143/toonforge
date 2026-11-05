"""ToonForge low-level API client for the Meta Model API.

Wraps the verified connector helper
(~/workspace/custom-connectors/custom.meta-model-api/bin/meta_api.py)
and adds vision input (base64 image messages) plus a robust JSON extractor
for Spark's structured outputs.

Auth: bearer key via authd surrogate — this module never sees a raw secret.
Dev tier only: muse-spark-1.3-contributor. Standard tier is reserved for
final/demo runs and must be chosen explicitly by the caller.
"""

from __future__ import annotations

import base64
import io
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path.home() / "workspace/custom-connectors/custom.meta-model-api/bin"))
import meta_api  # noqa: E402  (verified connector helper: chat(), image())
sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response  # noqa: E402

HOST = "api.meta.ai"
BASE = f"https://{HOST}/v1"
CONNECTOR = "custom.meta-model-api"

MODEL_SPARK_DEV = "muse-spark-1.3-contributor"
MODEL_SPARK_FINAL = "muse-spark-1.3"
MODEL_IMAGE = "muse-image-1.0"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def chat(prompt: str, *, system: str | None = None,
         model: str = MODEL_SPARK_DEV, timeout: int = 180) -> tuple[str, dict]:
    """Text chat call. Returns (content, usage_dict)."""
    out = meta_api.chat(prompt, model=model, system=system, timeout=timeout)
    msg = out.get("choices", [{}])[0].get("message", {}).get("content", "")
    return msg, out.get("usage", {})


def _shrink_image(path: str, max_side: int = 768) -> bytes:
    """Downscale for vision input to keep token cost sane. Returns PNG bytes."""
    raw = Path(path).read_bytes()
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except ImportError:
        return raw  # no PIL: send as-is


def chat_vision(text: str, image_paths: list[str], *, system: str | None = None,
                model: str = MODEL_SPARK_DEV, timeout: int = 240) -> tuple[str, dict]:
    """Chat call with image(s) attached (OpenAI vision format, base64 data URLs).

    Returns (content, usage_dict).
    """
    content: list[dict] = [{"type": "text", "text": text}]
    for p in image_paths:
        b64 = base64.b64encode(_shrink_image(p)).decode()
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}})
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})
    payload = {"model": model, "messages": messages, "stream": False}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + "/chat/completions", data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    add_surrogate_to_request(req, CONNECTOR, allowed_hosts=[HOST])
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as resp:
        out = read_json_response(resp)
    msg = out["choices"][0]["message"]["content"]
    return msg, out.get("usage", {})


class ContentPolicyError(RuntimeError):
    """The image endpoint's content filter rejected the prompt.

    Attributes: prompt (the rejected prompt text).
    """
    def __init__(self, prompt: str):
        super().__init__("content_policy_violation")
        self.prompt = prompt


def generate_image(prompt: str, out_path: str, *,
                   model: str = MODEL_IMAGE, size: str = "1024x1792",
                   timeout: int = 300) -> str:
    """Text-to-image. Returns the saved path.

    Raises ContentPolicyError (carrying the prompt) when the endpoint's
    content filter rejects it, so callers can soften and retry.
    """
    import urllib.error
    try:
        return meta_api.image(prompt, out_path, model=model, size=size,
                              timeout=timeout)
    except urllib.error.HTTPError as e:
        body = ""
        if e.code == 400:
            try:
                body = e.read().decode(errors="replace")
            except Exception:
                pass
        if "content_policy_violation" in body:
            raise ContentPolicyError(prompt) from e
        raise


def extract_json(text: str) -> dict:
    """Pull the first top-level JSON object out of model output.

    Handles markdown fences and stray prose. Brace matching respects
    JSON string escapes.
    """
    t = text.strip()
    if t.startswith("```"):
        # strip one fenced block if the whole reply is fenced
        lines = t.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    start = t.find("{")
    if start < 0:
        raise ValueError("no JSON object found in model output")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return json.loads(t[start:i + 1])
    raise ValueError("unbalanced JSON in model output")
