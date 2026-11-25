"""Google Gemini Vision LLM provider using the google-genai SDK with Structured Output."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from src.llm.base import BaseVisionLLM, LLMSemanticResult

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "gemini-3.8-flash"
_FALLBACK_MODELS = ("gemini-3.6-flash", "gemini-3-flash-preview")

_SYSTEM_PROMPT = """You are an expert architectural CAD engineer.
Analyze the provided floor-plan image and optional extracted PDF text context.
Extract:
1. floor_name (if visible, e.g. 'Begane grond', '1e verdieping', 'Ground Floor')
2. elevation_peil_mm (floor elevation in mm relative to PEIL, e.g. -50 or 4400)
3. scale_ratio (if visible, e.g. '1:100')
4. All linear dimensions in mm (e.g. '< 6720 >' -> 6720, orientation 'horizontal' or 'vertical')
5. All rooms with their original name, Vietnamese translation (name_vn), category
   ('commercial', 'living', 'bedroom', 'bathroom', 'kitchen', 'corridor', 'utility', 'other'),
   and nominal area in m2 (convert comma decimals like '56,73 m2' to 56.73).
Be exact with numbers. Do not invent dimensions or areas that are not shown."""


def _load_dotenv_if_needed() -> None:
    """Load key=value pairs from project .env into os.environ if not already set."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


class GeminiVisionProvider(BaseVisionLLM):
    """Primary Vision LLM engine powered by Google Gemini (default: gemini-3-flash-preview)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        _load_dotenv_if_needed()
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model = model or os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)
        self._client = None

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("GEMINI_API_KEY is not set.")
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=15_000),
            )
        return self._client

    def analyze_floor_plan(
        self,
        image_path: str,
        context_text: str = "",
    ) -> LLMSemanticResult:
        """Send cropped floor-plan PNG + text context to Gemini with JSON schema enforcement."""
        from google.genai import types
        from PIL import Image

        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Floor plan image not found: {path}")

        client = self._get_client()
        image = Image.open(path)

        prompt = _SYSTEM_PROMPT
        if context_text.strip():
            prompt += f"\n\nExtracted PDF text hints:\n{context_text.strip()}"

        candidates = list(dict.fromkeys([self.model, *_FALLBACK_MODELS]))
        last_exc: Optional[Exception] = None

        for idx, model_name in enumerate(candidates):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[image, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=LLMSemanticResult,
                        temperature=0.0,
                    ),
                )
                if response.parsed is not None:
                    return response.parsed
                return LLMSemanticResult.model_validate_json(response.text)
            except Exception as exc:
                last_exc = exc
                msg = str(exc)
                is_transient = (
                    isinstance(exc, TimeoutError)
                    or "503" in msg
                    or "504" in msg
                    or "UNAVAILABLE" in msg
                    or "DEADLINE_EXCEEDED" in msg
                    or "429" in msg
                    or "timed out" in msg.lower()
                )
                if is_transient and idx < len(candidates) - 1:
                    logger.warning(
                        "Model %s unavailable (%s); falling back to %s",
                        model_name,
                        msg.splitlines()[0][:120],
                        candidates[idx + 1],
                    )
                    continue
                raise

        raise RuntimeError(f"All Gemini models failed: {last_exc}")
