"""Runtime configuration loaded from environment variables."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional


class ConfigError(ValueError):
    """Raised when runtime configuration is invalid."""


@dataclass
class AgentConfig:
    api_key: str = field(repr=False)
    base_url: str = "https://api.siliconflow.cn/v1"
    model: str = "Qwen/Qwen3-VL-8B-Instruct"
    screenshot_scale: float = 0.5
    settle_delay: float = 0.6
    qwen_timeout: float = 30.0
    reports_dir: Path = Path("reports")

    def __post_init__(self):
        if not self.api_key or not self.api_key.strip():
            raise ConfigError("OPENAI_API_KEY is required")
        if not self.base_url or not self.base_url.strip():
            raise ConfigError("OPENAI_BASE_URL must not be empty")
        if not self.model or not self.model.strip():
            raise ConfigError("MODEL must not be empty")

        self.screenshot_scale = self._parse_float(
            "SCREENSHOT_SCALE",
            self.screenshot_scale,
        )
        self.settle_delay = self._parse_float(
            "ACTION_SETTLE_DELAY",
            self.settle_delay,
        )
        self.qwen_timeout = self._parse_float(
            "QWEN_TIMEOUT_SECONDS",
            self.qwen_timeout,
        )

        if not 0 < self.screenshot_scale <= 1:
            raise ConfigError("SCREENSHOT_SCALE must be greater than 0 and at most 1")
        if self.settle_delay < 0:
            raise ConfigError("ACTION_SETTLE_DELAY must not be negative")
        if self.qwen_timeout <= 0:
            raise ConfigError("QWEN_TIMEOUT_SECONDS must be greater than 0")

        self.reports_dir = Path(self.reports_dir)
        if not str(self.reports_dir).strip():
            raise ConfigError("REPORTS_DIR must not be empty")

    @classmethod
    def from_env(
        cls,
        env: Optional[Mapping[str, str]] = None,
    ) -> "AgentConfig":
        source = os.environ if env is None else env
        return cls(
            api_key=source.get("OPENAI_API_KEY", "").strip(),
            base_url=source.get(
                "OPENAI_BASE_URL",
                "https://api.siliconflow.cn/v1",
            ).strip(),
            model=source.get(
                "MODEL",
                "Qwen/Qwen3-VL-8B-Instruct",
            ).strip(),
            screenshot_scale=source.get("SCREENSHOT_SCALE", 0.5),
            settle_delay=source.get("ACTION_SETTLE_DELAY", 0.6),
            qwen_timeout=source.get("QWEN_TIMEOUT_SECONDS", 30.0),
            reports_dir=source.get("REPORTS_DIR", "reports"),
        )

    def with_overrides(
        self,
        screenshot_scale=None,
        settle_delay=None,
        qwen_timeout=None,
        reports_dir=None,
        model=None,
    ) -> "AgentConfig":
        return AgentConfig(
            api_key=self.api_key,
            base_url=self.base_url,
            model=model if model is not None else self.model,
            screenshot_scale=(
                screenshot_scale
                if screenshot_scale is not None
                else self.screenshot_scale
            ),
            settle_delay=(
                settle_delay
                if settle_delay is not None
                else self.settle_delay
            ),
            qwen_timeout=(
                qwen_timeout
                if qwen_timeout is not None
                else self.qwen_timeout
            ),
            reports_dir=(
                reports_dir
                if reports_dir is not None
                else self.reports_dir
            ),
        )

    @staticmethod
    def _parse_float(name: str, value) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as error:
            raise ConfigError(f"{name} must be a number") from error
