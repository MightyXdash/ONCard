from __future__ import annotations

import base64
import json
from pathlib import Path
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

    def remove_model(self, model_tag: str, on_output=None) -> bool:
        cmd = ["ollama", "rm", model_tag]
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

    def installed_tags(self, timeout: int = 5) -> set[str]:
        try:
            response = requests.get(f"{self.host}/api/tags", timeout=timeout)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise OllamaError(f"Could not list installed models: {exc}") from exc

        tags: set[str] = set()
        for item in body.get("models", []):
            tag = str(item.get("name") or item.get("model") or "").strip()
            if not tag:
                continue
            tags.add(tag)
        return tags

    @staticmethod
    def _build_options(temperature: float, extra_options: dict | None = None) -> dict:
        options = {"temperature": temperature}
        if extra_options:
            options.update(extra_options)
        return options

    @staticmethod
    def _encode_images(image_paths: list[str] | None = None) -> list[str]:
        encoded: list[str] = []
        for image_path in image_paths or []:
            encoded.append(base64.b64encode(Path(image_path).read_bytes()).decode("ascii"))
        return encoded

    def chat(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        *,
        image_paths: list[str] | None = None,
        temperature: float = 0.2,
        extra_options: dict | None = None,
        timeout: int = 180,
        response_format: dict | None = None,
    ) -> str:
        payload = {
            "model": model,
            "stream": False,
            "options": self._build_options(temperature, extra_options),
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": self._encode_images(image_paths),
                },
            ],
        }
        if response_format is not None:
            payload["format"] = response_format
        try:
            response = requests.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
            response.raise_for_status()
            body = response.json()
            return str(body.get("message", {}).get("content", "")).strip()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise OllamaError(f"Chat failed: {exc}") from exc

    def chat_messages(
        self,
        model: str,
        messages: list[dict],
        *,
        temperature: float = 0.2,
        extra_options: dict | None = None,
        timeout: int = 180,
        tools: list[dict] | None = None,
        response_format: dict | None = None,
        stream: bool = False,
    ) -> dict:
        payload = {
            "model": model,
            "stream": stream,
            "options": self._build_options(temperature, extra_options),
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        if response_format is not None:
            payload["format"] = response_format
        try:
            response = requests.post(f"{self.host}/api/chat", json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise OllamaError(f"Chat failed: {exc}") from exc

    def structured_chat(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        temperature: float = 0.0,
        timeout: int = 120,
        image_paths: list[str] | None = None,
        extra_options: dict | None = None,
    ) -> dict:
        try:
            content = self.chat(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_paths=image_paths,
                temperature=temperature,
                extra_options=extra_options,
                timeout=timeout,
                response_format=schema,
            ) or "{}"
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Structured chat failed: {exc}") from exc

    def stream_chat(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        *,
        image_paths: list[str] | None = None,
        temperature: float = 0.2,
        extra_options: dict | None = None,
        response_format: dict | None = None,
        timeout: int = 180,
        should_stop=None,
    ) -> Iterator[str]:
        payload = {
            "model": model,
            "stream": True,
            "options": self._build_options(temperature, extra_options),
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": self._encode_images(image_paths),
                },
            ],
        }
        if response_format is not None:
            payload["format"] = response_format
        try:
            with requests.post(f"{self.host}/api/chat", json=payload, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if should_stop and should_stop():
                        break
                    if not line:
                        continue
                    obj = json.loads(line.decode("utf-8"))
                    chunk = obj.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise OllamaError(f"Streaming chat failed: {exc}") from exc

    def stream_structured_chat(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema: dict,
        *,
        image_paths: list[str] | None = None,
        temperature: float = 0.0,
        extra_options: dict | None = None,
        timeout: int = 180,
        should_stop=None,
    ) -> dict:
        parts: list[str] = []
        try:
            for chunk in self.stream_chat(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_paths=image_paths,
                temperature=temperature,
                extra_options=extra_options,
                response_format=schema,
                timeout=timeout,
                should_stop=should_stop,
            ):
                parts.append(chunk)
            content = "".join(parts).strip() or "{}"
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaError(f"Streaming structured chat failed: {exc}") from exc

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

    def embed_text(self, model_tag: str, text: str, timeout: int = 120) -> list[float]:
        payload = {"model": model_tag, "input": text}
        try:
            response = requests.post(f"{self.host}/api/embed", json=payload, timeout=timeout)
            if response.status_code == 404:
                response = requests.post(f"{self.host}/api/embeddings", json={"model": model_tag, "prompt": text}, timeout=timeout)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise OllamaError(f"Embedding failed: {exc}") from exc

        vector = body.get("embedding")
        if vector is None:
            embeddings = body.get("embeddings")
            if isinstance(embeddings, list) and embeddings:
                vector = embeddings[0]
        if not isinstance(vector, list):
            raise OllamaError("Embedding failed: Ollama returned no embedding vector.")
        try:
            return [float(item) for item in vector]
        except (TypeError, ValueError) as exc:
            raise OllamaError(f"Embedding failed: invalid embedding vector: {exc}") from exc
