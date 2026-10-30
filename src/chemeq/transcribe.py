"""Vision-model transcription of a chemistry worksheet photo.

The model is deliberately used as a *transcriber only*.  It must not grade or
"fix" a student's wrong equation; the deterministic checker (``compare.py``)
does the grading.  Keeping this boundary explicit is what makes the result
explainable and testable.
"""

from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageOps

from .config import Config
from .models import (
    Transcription,
    TranscriptionResult,
    Usage,
)
from .pricing import estimate_cost

try:  # optional HEIC support (iPhone photos)
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - pillow-heif is a normal dependency
    pillow_heif = None  # type: ignore[assignment]


class ImageError(ValueError):
    pass


class TranscriptionError(RuntimeError):
    pass


SYSTEM_PROMPT = """你是高中化学作业转写员。你的唯一任务是转写图片中的信息，不做批改、不纠正、不补全。

规则：
1. 读出卷面姓名、学号/座号、班级；看不清就留空，并降低 confidence。
2. 逐题转写学生手写的化学方程式，保持原样：系数、下标、电荷、反应条件、箭头、↑↓、状态符号都要保留。
3. 学生写错的产物、系数、条件，照原样转写，绝对不要改成正确答案。
4. 只转写学生作答的内容；印刷的题目文字不要转写。
5. 看不清的字符用 ? 表示，并在 notes 里说明。
6. 题号必须以卷面印刷题号为准（如 6、7、8），不要从 1 重新编号；同一题下有多个方程式时写成 6(1)、6(2)。
7. 条件写在等号/箭头上方时，转写成 --条件--> 形式（例如 2NaHCO3 =△= Na2CO3 写成 2NaHCO3 --加热--> Na2CO3）。
8. 只输出 JSON，不要 markdown，不要解释。

JSON 结构：
{"student":{"name":"","no":"","class":"","confidence":0.0},"equations":[{"qno":"","raw":"","confidence":0.0}],"notes":""}
"""

USER_PROMPT = "请转写这张化学方程式作业。只输出 JSON。"


def prepare_image(source: bytes | str | Path, max_edge: int = 1500, quality: int = 85) -> bytes:
    """Rotate, strip EXIF, convert to JPEG and downscale a page photo."""

    if isinstance(source, (str, Path)):
        try:
            raw = Path(source).read_bytes()
        except OSError as exc:
            raise ImageError(f"无法读取图片：{exc}") from exc
    else:
        raw = source
    if not raw:
        raise ImageError("图片为空")
    if len(raw) > 25 * 1024 * 1024:
        raise ImageError("图片超过 25MB，请压缩后再上传")
    try:
        image = Image.open(io.BytesIO(raw))
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
    except Exception as exc:  # Pillow raises a variety of exception types
        raise ImageError(f"无法识别图片格式：{exc}") from exc

    image.thumbnail((max_edge, max_edge), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise TranscriptionError("模型没有返回 JSON")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise TranscriptionError(f"模型返回的 JSON 不完整：{exc}") from exc
    if not isinstance(payload, dict):
        raise TranscriptionError("模型返回的 JSON 不是对象")
    return payload


def _usage_from_response(data: dict[str, Any]) -> Usage:
    usage = data.get("usage") or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or prompt + completion)
    details = usage.get("prompt_tokens_details") or {}
    cache_hit = int(
        usage.get("prompt_cache_hit_tokens")
        or details.get("cached_tokens")
        or 0
    )
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cache_hit_tokens=cache_hit,
    )


class TranscriptionClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _endpoint(self) -> str:
        return self.cfg.base_url.rstrip("/") + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.cfg.api_key:
            raise TranscriptionError("还没有填写 API Key，请先在设置里填写并测试连接")
        payload = dict(payload)
        last_error = ""
        for attempt in range(3):
            try:
                response = httpx.post(
                    self._endpoint(),
                    headers=self._headers(),
                    json=payload,
                    timeout=self.cfg.timeout_seconds,
                )
            except httpx.HTTPError as exc:
                raise TranscriptionError(f"连接模型服务失败：{exc}") from exc

            if response.status_code == 200:
                try:
                    return response.json()
                except json.JSONDecodeError as exc:
                    raise TranscriptionError("模型服务返回了非 JSON 响应") from exc

            body = response.text[:800]
            lower = body.lower()
            # Some OpenAI-compatible providers reject DeepSeek-specific fields.
            if response.status_code == 400 and "thinking" in payload and "thinking" in lower:
                payload.pop("thinking", None)
                last_error = body
                continue
            if (
                response.status_code == 400
                and "response_format" in payload
                and "response_format" in lower
            ):
                payload.pop("response_format", None)
                last_error = body
                continue
            if response.status_code in (401, 403):
                raise TranscriptionError("API Key 无效或没有权限（401/403），请检查 Key 和模型名")
            if response.status_code == 402:
                raise TranscriptionError("模型账户余额不足（402），请充值后再试")
            if response.status_code == 429:
                last_error = body
                time.sleep(1.5 * (attempt + 1))
                continue
            if 500 <= response.status_code < 600:
                last_error = body
                time.sleep(1.0 * (attempt + 1))
                continue
            raise TranscriptionError(f"模型接口返回 {response.status_code}：{body}")
        raise TranscriptionError(f"模型服务暂时不可用：{last_error}")

    def transcribe(
        self, image_bytes: bytes, *, page_no: int = 1, page_count: int = 1
    ) -> TranscriptionResult:
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        if page_count > 1:
            user_text = f"这是同一份作业的第 {page_no} 页，共 {page_count} 页。{USER_PROMPT}"
        else:
            user_text = USER_PROMPT
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/jpeg;base64," + image_b64,
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        started = time.time()
        data = self._post(payload)
        latency_ms = int((time.time() - started) * 1000)
        choices = data.get("choices") or []
        if not choices:
            raise TranscriptionError("模型没有返回 choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        content = content or ""
        payload_json = _extract_json(content)
        try:
            transcription = Transcription.model_validate(payload_json)
        except Exception as exc:
            raise TranscriptionError(f"转写结果字段不完整：{exc}") from exc
        usage = _usage_from_response(data)
        model = str(data.get("model") or self.cfg.model)
        cost = estimate_cost(
            model,
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.cache_hit_tokens,
        )
        return TranscriptionResult(
            transcription=transcription,
            usage=usage,
            model=model,
            cost_cny=cost,
            latency_ms=latency_ms,
            raw_text=content,
        )


def test_connection(cfg: Config) -> dict[str, Any]:
    """Cheap text-only call used by the settings page."""

    if not cfg.api_key:
        return {"ok": False, "error": "还没有填写 API Key"}
    payload: dict[str, Any] = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": "只输出 JSON。"},
            {"role": "user", "content": '请输出 JSON：{"ok": true}'},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 30,
        "temperature": 0,
        "thinking": {"type": "disabled"},
        "stream": False,
    }
    endpoint = cfg.base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"}
    started = time.time()
    for _attempt in range(2):
        try:
            response = httpx.post(endpoint, headers=headers, json=payload, timeout=30)
        except httpx.HTTPError as exc:
            return {"ok": False, "error": f"连接失败：{exc}"}
        if response.status_code == 200:
            return {
                "ok": True,
                "model": cfg.model,
                "latency_ms": int((time.time() - started) * 1000),
            }
        body = response.text[:500]
        if response.status_code == 400 and "thinking" in payload and "thinking" in body.lower():
            payload.pop("thinking", None)
            continue
        if (
            response.status_code == 400
            and "response_format" in payload
            and "response_format" in body.lower()
        ):
            payload.pop("response_format", None)
            continue
        return {"ok": False, "error": f"HTTP {response.status_code}：{body}"}
    return {"ok": False, "error": "模型服务拒绝了连接测试"}
