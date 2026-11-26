"""SiliconFlow Qwen vision provider."""

import base64
import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Optional

from openai import OpenAI

from opskestrel.providers.base import VisionProvider, VisionProviderError


class QwenVisionProvider(VisionProvider):
    """Verify screenshots with a Qwen vision model."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 30.0,
        client: Optional[Any] = None,
    ):
        timeout = float(timeout)
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0")

        self.model = model or os.getenv(
            "MODEL",
            "Qwen/Qwen3-VL-8B-Instruct",
        )

        if client is None:
            resolved_api_key = api_key or os.getenv("OPENAI_API_KEY")
            if not resolved_api_key:
                raise ValueError("OPENAI_API_KEY is required")

            client = OpenAI(
                api_key=resolved_api_key,
                base_url=base_url or os.getenv("OPENAI_BASE_URL"),
                timeout=timeout,
            )

        self.client = client

    def verify(self, image_path: str, statement: str) -> bool:
        path = Path(image_path)
        if not path.is_file():
            raise VisionProviderError(f"image does not exist: {image_path}")

        if not statement or not statement.strip():
            raise VisionProviderError("verification statement must not be empty")

        try:
            image_data = base64.b64encode(path.read_bytes()).decode("ascii")
            media_type = mimetypes.guess_type(path.name)[0] or "image/png"
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "Analyze the image and answer whether the "
                                    f"following statement is true: {statement}\n"
                                    "Return exactly true or false."
                                ),
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": (
                                        f"data:{media_type};base64,{image_data}"
                                    )
                                },
                            },
                        ],
                    }
                ],
                temperature=0.0,
            )
        except Exception as error:
            raise VisionProviderError(
                f"Qwen verification request failed: {error}"
            ) from error

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as error:
            raise VisionProviderError(
                "Qwen returned an invalid response"
            ) from error

        normalized = str(content).strip().lower()
        match = re.search(r"\b(true|false)\b", normalized)
        if match is None:
            raise VisionProviderError(
                f"Qwen returned an unparseable result: {content!r}"
            )

        return match.group(1) == "true"
