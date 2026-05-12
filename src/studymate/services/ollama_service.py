from __future__ import annotations

import base64
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterator

import requests


class OllamaError(RuntimeError):
    pass


class OllamaService:
    LOCAL_DEFAULT_HOST = "http://127.0.0.1:11434"
    CLOUD_HOST = "https://ollama.com"
    CLOUD_SAFE_OPTION_KEYS = {
        "temperature",
        "top_p",
        "top_k",
        "min_p",
        "repeat_penalty",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "stop",
        "num_predict",
    }

    def __init__(self, host: str = LOCAL_DEFAULT_HOST) -> None:
        self.local_host = str(host or self.LOCAL_DEFAULT_HOST).rstrip("/")
        self.cloud_host = self.CLOUD_HOST
        self.cloud_enabled = False
        self.cloud_api_key = ""
        self.host = self.local_host

    def configure_from_ai_settings(self, ai_settings: dict | None) -> None:
        settings = ai_settings or {}
        self.set_cloud_mode(
            enabled=bool(settings.get("ollama_cloud_enabled", False)),
            api_key=str(settings.get("ollama_cloud_api_key", "")).strip(),
        )

    def set_cloud_mode(self, *, enabled: bool, api_key: str | None = None) -> None:
        if api_key is not None:
            self.cloud_api_key = str(api_key or "").strip()
        self.cloud_enabled = bool(enabled)
        self.host = self.cloud_host if self.cloud_enabled else self.local_host

    def _resolve_host(self, *, use_cloud: bool | None = None) -> str:
        if use_cloud is None:
            use_cloud = self.cloud_enabled
        return self.cloud_host if bool(use_cloud) else self.local_host

    def _headers(self, host: str, *, api_key_override: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if host.startswith(self.cloud_host):
            key = str(api_key_override if api_key_override is not None else self.cloud_api_key).strip()
            if key:
                headers["Authorization"] = f"Bearer {key}"
        return headers

    def _is_cloud_host(self, host: str) -> bool:
        return str(host or "").startswith(self.cloud_host)

    @staticmethod
    def _http_error_detail(response: requests.Response | None) -> str:
        if response is None:
            return ""
        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = str(payload.get("error") or payload.get("message") or "").strip()
        except (json.JSONDecodeError, ValueError):
            detail = ""
        if not detail:
            detail = " ".join(str(response.text or "").split()).strip()
        if detail:
            return detail[:360]
        return f"HTTP {response.status_code}"

    def _sanitize_options_for_host(self, options: dict[str, Any], host: str) -> dict[str, Any]:
        if not self._is_cloud_host(host):
            return dict(options)
        cleaned: dict[str, Any] = {}
        for key, value in options.items():
            normalized = str(key or "").strip()
            if normalized in self.CLOUD_SAFE_OPTION_KEYS:
                cleaned[normalized] = value
        return cleaned

    def _payload_variants(self, payload: dict[str, Any], host: str) -> list[dict[str, Any]]:
        base = dict(payload)
        variants = [base]
        if not self._is_cloud_host(host):
            return variants
        without_options = dict(base)
        without_options.pop("options", None)
        without_format = dict(base)
        without_format.pop("format", None)
        without_both = dict(without_options)
        without_both.pop("format", None)
        variants.extend([without_options, without_format, without_both])
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in variants:
            try:
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
            except TypeError:
                marker = repr(item)
            if marker in seen:
                continue
            seen.add(marker)
            unique.append(item)
        return unique

    @staticmethod
    def _extract_message_content(body: dict) -> str:
        return str(body.get("message", {}).get("content", "")).strip()

    def _post_chat_json(
        self,
        *,
        host: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: int,
    ) -> dict:
        variants = self._payload_variants(payload, host)
        for index, candidate in enumerate(variants):
            try:
                response = requests.post(f"{host}/api/chat", json=candidate, headers=headers, timeout=timeout)
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                can_retry = self._is_cloud_host(host) and status_code == 400 and index < (len(variants) - 1)
                if can_retry:
                    continue
                detail = self._http_error_detail(exc.response)
                raise OllamaError(f"Chat failed: {detail or exc}") from exc
            except (requests.RequestException, json.JSONDecodeError) as exc:
                raise OllamaError(f"Chat failed: {exc}") from exc
        raise OllamaError("Chat failed: no valid cloud payload variant succeeded.")

    def _iter_stream_chat(
        self,
        *,
        host: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: int,
        should_stop,
    ) -> Iterator[str]:
        variants = self._payload_variants(payload, host)
        for index, candidate in enumerate(variants):
            try:
                with requests.post(f"{host}/api/chat", json=candidate, headers=headers, stream=True, timeout=timeout) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if should_stop and should_stop():
                            return
                        if not line:
                            continue
                        obj = json.loads(line.decode("utf-8"))
                        chunk = str(obj.get("message", {}).get("content", ""))
                        if chunk != "":
                            yield chunk
                    return
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                can_retry = self._is_cloud_host(host) and status_code == 400 and index < (len(variants) - 1)
                if can_retry:
                    continue
                detail = self._http_error_detail(exc.response)
                raise OllamaError(f"Streaming chat failed: {detail or exc}") from exc
            except (requests.RequestException, json.JSONDecodeError) as exc:
                raise OllamaError(f"Streaming chat failed: {exc}") from exc
        raise OllamaError("Streaming chat failed: no valid cloud payload variant succeeded.")

    def _iter_stream_chat_events(
        self,
        *,
        host: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: int,
        should_stop,
    ) -> Iterator[tuple[str, str]]:
        variants = self._payload_variants(payload, host)
        for index, candidate in enumerate(variants):
            try:
                with requests.post(f"{host}/api/chat", json=candidate, headers=headers, stream=True, timeout=timeout) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if should_stop and should_stop():
                            return
                        if not line:
                            continue
                        obj = json.loads(line.decode("utf-8"))
                        message = obj.get("message", {})
                        if not isinstance(message, dict):
                            continue
                        thinking = str(
                            message.get("thinking")
                            or message.get("reasoning")
                            or message.get("reasoning_content")
                            or ""
                        )
                        content = str(message.get("content", ""))
                        if thinking:
                            yield ("thinking", thinking)
                        if content:
                            yield ("content", content)
                    return
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                can_retry = self._is_cloud_host(host) and status_code == 400 and index < (len(variants) - 1)
                if can_retry:
                    continue
                detail = self._http_error_detail(exc.response)
                raise OllamaError(f"Streaming chat failed: {detail or exc}") from exc
            except (requests.RequestException, json.JSONDecodeError) as exc:
                raise OllamaError(f"Streaming chat failed: {exc}") from exc
        raise OllamaError("Streaming chat failed: no valid cloud payload variant succeeded.")

    @staticmethod
    def _parse_json_object_loose(content: str) -> dict[str, Any] | None:
        text = str(content or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE):
            snippet = str(match.group(1) or "").strip()
            if not snippet:
                continue
            try:
                parsed = json.loads(snippet)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            snippet = text[start : end + 1]
            try:
                parsed = json.loads(snippet)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return None
        return None

    @staticmethod
    def _extract_tags(body: dict) -> set[str]:
        tags: set[str] = set()
        for item in body.get("models", []):
            tag = str(item.get("name") or item.get("model") or "").strip()
            if tag:
                tags.add(tag)
        return tags

    def ping(self, timeout: int = 3, *, use_cloud: bool | None = None, api_key: str | None = None) -> bool:
        host = self._resolve_host(use_cloud=use_cloud)
        headers = self._headers(host, api_key_override=api_key)
        try:
            response = requests.get(f"{host}/api/tags", headers=headers, timeout=timeout)
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

    def installed_tags(self, timeout: int = 5, *, use_cloud: bool | None = None, api_key: str | None = None) -> set[str]:
        host = self._resolve_host(use_cloud=use_cloud)
        headers = self._headers(host, api_key_override=api_key)
        try:
            response = requests.get(f"{host}/api/tags", headers=headers, timeout=timeout)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise OllamaError(f"Could not list installed models: {exc}") from exc
        return self._extract_tags(body)

    def cloud_model_tags(self, api_key: str, timeout: int = 8) -> list[str]:
        tags = self.installed_tags(timeout=timeout, use_cloud=True, api_key=api_key)
        return sorted(tags, key=lambda value: value.lower())

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
        think: bool = False,
    ) -> str:
        host = self._resolve_host()
        headers = self._headers(host)
        options = self._sanitize_options_for_host(self._build_options(temperature, extra_options), host)
        payload = {
            "model": model,
            "stream": False,
            "think": bool(think),
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": self._encode_images(image_paths),
                },
            ],
        }
        if options:
            payload["options"] = options
        if response_format is not None:
            payload["format"] = response_format
        body = self._post_chat_json(host=host, headers=headers, payload=payload, timeout=timeout)
        return self._extract_message_content(body)

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
        think: bool = False,
    ) -> dict:
        host = self._resolve_host()
        headers = self._headers(host)
        options = self._sanitize_options_for_host(self._build_options(temperature, extra_options), host)
        payload = {
            "model": model,
            "stream": stream,
            "think": bool(think),
            "messages": messages,
        }
        if options:
            payload["options"] = options
        if tools:
            payload["tools"] = tools
        if response_format is not None:
            payload["format"] = response_format
        return self._post_chat_json(host=host, headers=headers, payload=payload, timeout=timeout)

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
        parsed = self._parse_json_object_loose(content)
        if parsed is None:
            retry_prompt = (
                f"{user_prompt.strip()}\n\n"
                "Return only a valid JSON object matching the requested schema. "
                "Do not include markdown, prose, or code fences."
            )
            retry_content = self.chat(
                model=model,
                system_prompt=system_prompt,
                user_prompt=retry_prompt,
                image_paths=image_paths,
                temperature=0.0,
                extra_options=extra_options,
                timeout=timeout,
                response_format=None,
            ) or "{}"
            parsed = self._parse_json_object_loose(retry_content)
        if parsed is None:
            preview = " ".join(content.split())[:180]
            raise OllamaError(f"Structured chat failed: model did not return valid JSON. Preview: {preview}")
        return parsed

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
        think: bool = False,
    ) -> Iterator[str]:
        host = self._resolve_host()
        headers = self._headers(host)
        options = self._sanitize_options_for_host(self._build_options(temperature, extra_options), host)
        payload = {
            "model": model,
            "stream": True,
            "think": bool(think),
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": self._encode_images(image_paths),
                },
            ],
        }
        if options:
            payload["options"] = options
        if response_format is not None:
            payload["format"] = response_format
        yield from self._iter_stream_chat(
            host=host,
            headers=headers,
            payload=payload,
            timeout=timeout,
            should_stop=should_stop,
        )

    def stream_chat_events(
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
        think: bool = False,
    ) -> Iterator[tuple[str, str]]:
        host = self._resolve_host()
        headers = self._headers(host)
        options = self._sanitize_options_for_host(self._build_options(temperature, extra_options), host)
        payload = {
            "model": model,
            "stream": True,
            "think": bool(think),
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": user_prompt,
                    "images": self._encode_images(image_paths),
                },
            ],
        }
        if options:
            payload["options"] = options
        if response_format is not None:
            payload["format"] = response_format
        yield from self._iter_stream_chat_events(
            host=host,
            headers=headers,
            payload=payload,
            timeout=timeout,
            should_stop=should_stop,
        )

    def stream_prompt(
        self,
        model: str,
        prompt: str,
        *,
        temperature: float = 0.2,
        extra_options: dict | None = None,
        timeout: int = 180,
        should_stop=None,
        think: bool = False,
    ) -> Iterator[str]:
        host = self._resolve_host()
        headers = self._headers(host)
        options = self._sanitize_options_for_host(self._build_options(temperature, extra_options), host)
        payload: dict[str, Any] = {
            "model": model,
            "stream": True,
            "think": bool(think),
            "prompt": prompt,
        }
        if options:
            payload["options"] = options
        try:
            with requests.post(f"{host}/api/generate", json=payload, headers=headers, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if should_stop and should_stop():
                        return
                    if not line:
                        continue
                    obj = json.loads(line.decode("utf-8"))
                    chunk = str(obj.get("response", ""))
                    if chunk:
                        yield chunk
        except requests.HTTPError as exc:
            detail = self._http_error_detail(exc.response)
            raise OllamaError(f"Streaming generate failed: {detail or exc}") from exc
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise OllamaError(f"Streaming generate failed: {exc}") from exc

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
        parsed = self._parse_json_object_loose(content)
        if parsed is None:
            parsed = self.structured_chat(
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema,
                image_paths=image_paths,
                temperature=temperature,
                extra_options=extra_options,
                timeout=timeout,
            )
        if parsed is None:
            preview = " ".join(content.split())[:180]
            raise OllamaError(f"Streaming structured chat failed: invalid JSON response. Preview: {preview}")
        return parsed

    def benchmark_tps(self, model: str, prompt: str, timeout: int = 120) -> float:
        payload = {"model": model, "stream": False, "think": False, "prompt": prompt, "options": {"temperature": 0}}
        host = self._resolve_host()
        headers = self._headers(host)
        try:
            response = requests.post(f"{host}/api/generate", json=payload, headers=headers, timeout=timeout)
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
        host = self._resolve_host(use_cloud=False)
        headers = self._headers(host)
        body: dict | None = None
        try:
            response = requests.post(f"{host}/api/embed", json=payload, headers=headers, timeout=timeout)
            if response.status_code == 404:
                response = requests.post(
                    f"{host}/api/embeddings",
                    json={"model": model_tag, "prompt": text},
                    headers=headers,
                    timeout=timeout,
                )
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, json.JSONDecodeError) as exc:
            raise OllamaError(f"Embedding failed (local Ollama): {exc}") from exc

        if body is None:
            raise OllamaError("Embedding failed (local Ollama): no response body.")

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
