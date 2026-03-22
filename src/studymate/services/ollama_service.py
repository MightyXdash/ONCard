from __future__ import annotations

import json
import subprocess
from typing import Iterator

import requests


class OllamaError(RuntimeError):
    pass


class OllamaService:
    def __init__(self, host: str = "http://127.0.0.1:11434") -> None:
        self.host = host.rstrip("/")

    def ping(self, timeout: int = 3) -> bool:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=timeout)
            return response.ok
        except requests.RequestException:
            return False

    def pull_model(self, model_tag: str, on_output=None) -> bool:
        cmd = ["ollama", "pull", model_tag]
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            )
        except FileNotFoundError:
            if on_output:
                on_output("Ollama CLI not found. Install Ollama and restart setup.")
            return False
        if process.stdout:
            for line in process.stdout:
                if on_output:
                    on_output(line.strip())
        return process.wait() == 0

    def structured_chat(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float = 0.0,
        timeout: int = 120,
    ) -> dict:
        payload = {
            "model": model,
            "stream": False,
            "format": schema,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            response = requests.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
            response.raise_for_status()
            body = response.json()
            content = body.get("message", {}).get("content", "{}").strip()
            return json.loads(content)
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise OllamaError(f"Structured chat failed: {exc}") from exc

    def stream_chat(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        timeout: int = 180,
    ) -> Iterator[str]:
        payload = {
            "model": model,
            "stream": True,
            "options": {"temperature": temperature},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            with requests.post(f"{self.host}/api/chat", json=payload, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    obj = json.loads(line.decode("utf-8"))
                    chunk = obj.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise OllamaError(f"Streaming chat failed: {exc}") from exc

    def benchmark_tps(self, model: str, prompt: str, timeout: int = 120) -> float:
        payload = {"model": model, "stream": False, "prompt": prompt, "options": {"temperature": 0}}
        try:
            response = requests.post(f"{self.host}/api/generate", json=payload, timeout=timeout)
            response.raise_for_status()
            body = response.json()
            eval_count = float(body.get("eval_count", 0))
            eval_duration_ns = float(body.get("eval_duration", 0))
            if eval_count <= 0 or eval_duration_ns <= 0:
                return 0.0
            seconds = eval_duration_ns / 1_000_000_000.0
            return round(eval_count / seconds, 2) if seconds > 0 else 0.0
        except requests.RequestException as exc:
            raise OllamaError(f"Benchmark failed: {exc}") from exc
