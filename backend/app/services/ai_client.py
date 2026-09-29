"""DeepSeek HTTP transport and offline test client."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Callable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AIGatewayError(RuntimeError):
    """Base error for AI request and response failures."""


class AIConfigurationError(AIGatewayError):
    pass


class AIProviderError(AIGatewayError):
    pass


class AIResponseError(AIGatewayError):
    pass


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout_seconds: float = 60
    max_retries: int = 2

    def __post_init__(self):
        if not self.base_url.startswith("https://"):
            raise AIConfigurationError("DeepSeek base_url must use HTTPS")
        if self.timeout_seconds <= 0:
            raise AIConfigurationError("DeepSeek timeout_seconds must be positive")
        if self.max_retries < 0:
            raise AIConfigurationError("DeepSeek max_retries cannot be negative")
        if not self.model.strip():
            raise AIConfigurationError("DeepSeek model must be non-empty")

    @classmethod
    def from_environment(cls, repository_root: Path) -> "DeepSeekConfig":
        config_path = Path(repository_root) / "config" / "ai.yaml.example"
        values = {}
        if config_path.is_file():
            import yaml

            values = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        key_name = values.get("api_key_env", "DEEPSEEK_API_KEY")
        return cls(
            api_key=os.environ.get(key_name, ""),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", values.get("base_url", "https://api.deepseek.com")),
            model=os.environ.get("DEEPSEEK_MODEL", values.get("model", "deepseek-flash")),
            timeout_seconds=float(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", values.get("timeout_seconds", 60))),
            max_retries=int(os.environ.get("DEEPSEEK_MAX_RETRIES", values.get("max_retries", 2))),
        )


class DeepSeekClient:
    """Small OpenAI-compatible HTTP client with bounded transient retries."""

    def __init__(
        self,
        config: DeepSeekConfig,
        opener: Callable = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.opener = opener
        self.sleeper = sleeper

    def complete(self, messages: list[dict], output_schema: dict) -> str:
        if not self.config.api_key.strip():
            raise AIConfigurationError("DEEPSEEK_API_KEY is required for DeepSeek requests")
        body = json.dumps(
            {
                "model": self.config.model,
                "messages": messages,
                "response_format": {"type": "json_object"},
            },
            ensure_ascii=False,
        ).encode("utf-8")
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        request = Request(
            endpoint,
            data=body,
            headers={
                "Authorization": "Bearer {}".format(self.config.api_key),
                "Content-Type": "application/json",
            },
            method="POST",
        )

        for attempt in range(self.config.max_retries + 1):
            try:
                with self.opener(request, timeout=self.config.timeout_seconds) as response:
                    response_body = response.read()
                payload = json.loads(response_body.decode("utf-8"))
                try:
                    content = payload["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as error:
                    raise AIResponseError("DeepSeek returned an incomplete chat response") from error
                if not isinstance(content, str):
                    raise AIResponseError("DeepSeek returned non-text message content")
                return content
            except HTTPError as error:
                retryable = error.code in {408, 425, 429} or error.code >= 500
                if retryable and attempt < self.config.max_retries:
                    self._wait(attempt)
                    continue
                raise AIProviderError(
                    "DeepSeek returned HTTP {}{}".format(
                        error.code, " after retries" if retryable else ""
                    )
                ) from error
            except (TimeoutError, URLError, OSError) as error:
                if attempt < self.config.max_retries:
                    self._wait(attempt)
                    continue
                raise AIProviderError(
                    "DeepSeek request failed after {} attempt(s)".format(attempt + 1)
                ) from error
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise AIResponseError("DeepSeek returned an invalid JSON envelope") from error
        raise AIProviderError("DeepSeek request did not complete")

    def _wait(self, attempt: int) -> None:
        self.sleeper(min(0.25 * (2 ** attempt), 2.0))


class MockDeepSeekClient:
    """Offline client for deterministic tests; it never opens a network connection."""

    def __init__(self, responses: Optional[dict] = None):
        self.responses = responses or {}
        self.calls = []

    def complete(self, messages: list[dict], output_schema: dict) -> str:
        task_name = messages[0]["content"].split("Task: ", 1)[1].splitlines()[0]
        self.calls.append(task_name)
        if task_name not in self.responses:
            raise AIResponseError("Mock has no response for task '{}'".format(task_name))
        response = self.responses[task_name]
        return response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
