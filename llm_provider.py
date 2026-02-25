import json
import logging
import os
import socket
import urllib.error
import urllib.request
import dotenv
from dataclasses import dataclass
from typing import Optional

dotenv.load_dotenv()


@dataclass
class LLMClient:
    provider: str
    model: str
    api_key: Optional[str] = None
    base_url: str = "http://localhost:11434"
    timeout_seconds: int = 300
    ollama_num_ctx: Optional[int] = None

    def generate(self, prompt: str, response_mime_type: Optional[str] = None) -> str:
        logger = logging.getLogger(__name__)
        try:
            if self.provider == "gemini":
                from google import genai

                if not self.api_key:
                    raise ValueError("GOOGLE_API_KEY environment variable is not set")

                client = genai.Client(api_key=self.api_key)
                config = {"response_mime_type": response_mime_type} if response_mime_type else None
                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
                return (response.text or "").strip()

            if self.provider == "ollama":
                url = self.base_url.rstrip("/") + "/api/generate"
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                }
                if response_mime_type == "application/json":
                    payload["format"] = "json"
                if self.ollama_num_ctx:
                    payload["options"] = {"num_ctx": self.ollama_num_ctx}

                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    body = resp.read().decode("utf-8")
                out = json.loads(body)
                return str(out.get("response", "")).strip()

            raise ValueError(f"Unsupported LLM provider: {self.provider}")
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8")[:500]
            except Exception:
                body = ""
            logger.exception(
                "LLM HTTPError provider=%s model=%s url=%s status=%s body=%s",
                self.provider,
                self.model,
                getattr(self, "base_url", ""),
                exc.code,
                body,
            )
            raise
        except (urllib.error.URLError, socket.timeout) as exc:
            logger.exception(
                "LLM connection error provider=%s model=%s url=%s error=%s",
                self.provider,
                self.model,
                getattr(self, "base_url", ""),
                exc,
            )
            raise
        except Exception:
            logger.exception("LLM error provider=%s model=%s", self.provider, self.model)
            raise


def get_llm_client() -> LLMClient:
    provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    model = os.getenv("LLM_MODEL", "").strip()
    if not model:
        model = "llama3.1:8b" if provider == "ollama" else "gemini-flash-latest"

    api_key = os.getenv("GOOGLE_API_KEY")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    timeout_seconds = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "120"))
    num_ctx = os.getenv("OLLAMA_NUM_CTX")
    ollama_num_ctx = int(num_ctx) if num_ctx and num_ctx.isdigit() else None

    return LLMClient(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        ollama_num_ctx=ollama_num_ctx,
    )
