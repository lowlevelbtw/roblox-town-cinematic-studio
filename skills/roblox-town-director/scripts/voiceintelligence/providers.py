#!/usr/bin/env python3
# Project maintainer: RITVIK | Roblox Town Cinematic Studio
"""Provider-independent Voice Adapter System for Roblox Town Director.

Implements:
  - VoiceProviderAdapter: abstract provider interface with capability detection
  - ElevenLabsAdapter: real stdlib HTTP adapter (reads ELEVENLABS_API_KEY from env only)
  - OpenAITTSAdapter: modular future-compatible adapter contract
  - GoogleCloudTTSAdapter: modular future-compatible adapter contract
  - RecordedVoiceProviderAdapter: bridge to the local recorded voice backend
  - ProviderRegistry: selects providers honestly based on declared/verified capabilities
"""

from __future__ import annotations

import json
import math
import mimetypes
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


class VoiceProviderError(RuntimeError):
    """Base exception for provider adapter failures."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class ProviderAuthError(VoiceProviderError):
    """Authentication or missing credential failure."""


class ProviderQuotaError(VoiceProviderError):
    """Quota, rate-limit, or billing failure."""


class ProviderVoiceNotFoundError(VoiceProviderError):
    """Requested provider voice ID is invalid or unavailable."""


class ProviderCapabilityError(VoiceProviderError):
    """Requested feature is not supported by the active provider."""


class ProviderResponseError(VoiceProviderError):
    """Provider returned missing, empty, or malformed audio/data."""


class ProhibitedVoiceCloningError(ProviderCapabilityError):
    """Raised at the provider-adapter boundary when a voice-cloning request violates policy or is disabled."""


_PROHIBITED_CLONE_PATTERNS = (
    re.compile(r"\b(minor|child|kid|underage|teen|teenager|juvenile|schoolboy|schoolgirl|toddler|infant)\b", re.IGNORECASE),
    re.compile(r"\b(without\s+consent|no\s+consent|unconsented|unauthorized|impersonat\w*|deepfake|celebrity|politician|public\s+figure)\b", re.IGNORECASE),
)

def _validate_clone_request_safety(
    name: str,
    description: str,
    labels: Optional[Dict[str, str]] = None,
) -> None:
    """Defense-in-depth policy guard at the provider-adapter boundary."""
    combined = f"{name or ''} {description or ''}"
    for pat in _PROHIBITED_CLONE_PATTERNS:
        m = pat.search(combined)
        if m:
            raise ProhibitedVoiceCloningError(
                f"Prohibited voice-cloning request blocked at provider adapter boundary (matched policy term {m.group(0)!r}).",
                status_code=403,
                retryable=False,
            )
    if labels:
        for k, v in labels.items():
            kl = str(k).strip().lower()
            vl = str(v).strip().lower()
            if kl in ("minor", "is_minor", "underage") and vl in ("1", "true", "yes"):
                raise ProhibitedVoiceCloningError(
                    "Prohibited voice-cloning request blocked: minor/underage label is forbidden.",
                    status_code=403,
                    retryable=False,
                )
            if kl in ("consent_verified", "authorized", "explicit_authorization") and vl in ("0", "false", "no"):
                raise ProhibitedVoiceCloningError(
                    "Prohibited voice-cloning request blocked: explicit authorization/consent is false.",
                    status_code=403,
                    retryable=False,
                )
            if kl == "age":
                try:
                    if float(vl) < 18.0:
                        raise ProhibitedVoiceCloningError(
                            "Prohibited voice-cloning request blocked: speaker age < 18 is forbidden.",
                            status_code=403,
                            retryable=False,
                        )
                except ValueError:
                    pass
            for pat in _PROHIBITED_CLONE_PATTERNS:
                if pat.search(f"{k} {v}"):
                    raise ProhibitedVoiceCloningError(
                        "Prohibited voice-cloning request blocked via label content policy.",
                        status_code=403,
                        retryable=False,
                    )


@dataclass
class ProviderCapabilities:
    text_to_speech: bool = False
    voice_discovery: bool = False
    voice_design: bool = False
    authorized_voice_cloning: bool = False
    adjustable_controls: List[str] = field(default_factory=list)
    voice_design_controls: List[str] = field(default_factory=list)
    quota_reporting: bool = False
    recorded_audio_import: bool = False
    implemented: bool = True
    verified_live: bool = False


@dataclass
class SynthesisRequest:
    text: str
    provider_voice_id: str
    output_path: Path
    model_id: Optional[str] = None
    output_format: str = "mp3_44100_128"
    voice_settings: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SynthesisResult:
    provider: str
    provider_voice_id: str
    output_path: Path
    bytes_written: int
    content_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HTTPResponseData:
    status_code: int
    headers: Dict[str, str]
    body: bytes


TransportFn = Callable[
    [str, str, Dict[str, str], Optional[bytes], float],
    HTTPResponseData,
]


def _validate_http_url(url: str, *, allow_http: bool = False) -> str:
    parsed = urllib.parse.urlparse(url)
    allowed = ("https", "http") if allow_http else ("https",)
    if parsed.scheme not in allowed or not parsed.netloc:
        raise ValueError(f"Unsupported or invalid provider URL scheme/host: {url!r} (allowed: {allowed})")
    return url


def default_urllib_transport(
    method: str,
    url: str,
    headers: Dict[str, str],
    body: Optional[bytes],
    timeout: float,
) -> HTTPResponseData:
    _validate_http_url(url, allow_http=True)
    req = urllib.request.Request(url=url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return HTTPResponseData(
                status_code=int(getattr(resp, "status", 200)),
                headers={k.lower(): v for k, v in resp.headers.items()},
                body=resp.read(),
            )
    except urllib.error.HTTPError as exc:
        err_body = exc.read() if hasattr(exc, "read") else b""
        return HTTPResponseData(
            status_code=int(exc.code),
            headers={k.lower(): v for k, v in (exc.headers.items() if exc.headers else [])},
            body=err_body,
        )
    except urllib.error.URLError as exc:
        raise VoiceProviderError(f"Network error contacting provider: {exc.reason}", retryable=True) from exc


class VoiceProviderAdapter(ABC):
    provider_id: str = "base"
    display_name: str = "Base Provider"

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    @abstractmethod
    def is_configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def check_authentication(self) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_voices(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def synthesize_speech(self, request: SynthesisRequest) -> SynthesisResult:
        raise NotImplementedError

    def design_voice(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        raise ProviderCapabilityError(
            f"Provider {self.provider_id!r} does not support voice design."
        )

    def create_authorized_clone(
        self,
        *,
        name: str,
        description: str,
        sample_paths: List[Path],
        labels: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        _validate_clone_request_safety(name=name, description=description, labels=labels)
        raise ProhibitedVoiceCloningError(
            f"Provider {self.provider_id!r} remote voice cloning is unconditionally disabled in v0.2.0.",
            status_code=403,
            retryable=False,
        )

    def delete_voice(self, provider_voice_id: str) -> Dict[str, Any]:
        raise ProviderCapabilityError(
            f"Provider {self.provider_id!r} does not support remote voice deletion."
        )

    def get_quota(self) -> Dict[str, Any]:
        raise ProviderCapabilityError(
            f"Provider {self.provider_id!r} does not expose quota reporting."
        )


class ElevenLabsAdapter(VoiceProviderAdapter):
    """ElevenLabs REST API adapter using stdlib urllib (zero external packages).

    Reads credentials ONLY from the `ELEVENLABS_API_KEY` environment variable
    (or an explicit env var name). Never logs, prints, or persists the key.
    """

    provider_id = "elevenlabs"
    display_name = "ElevenLabs"
    DEFAULT_BASE_URL = "https://api.elevenlabs.io/v1"
    DEFAULT_MODEL_ID = "eleven_multilingual_v2"

    def __init__(
        self,
        *,
        api_key_env: str = "ELEVENLABS_API_KEY",
        credential_provider: Optional[Callable[[], Optional[str]]] = None,
        connector_authenticated: bool = False,
        base_url: str = DEFAULT_BASE_URL,
        timeout_sec: float = 30.0,
        allow_insecure_http: bool = False,
        transport: Optional[TransportFn] = None,
    ):
        if connector_authenticated and transport is None:
            raise ValueError(
                "connector_authenticated=True requires an explicit authenticated connector transport."
            )
        self.api_key_env = api_key_env
        self._credential_provider = credential_provider
        self.connector_authenticated = bool(connector_authenticated)
        self.base_url = _validate_http_url(base_url.rstrip("/"), allow_http=allow_insecure_http)
        if isinstance(timeout_sec, bool):
            raise ValueError(f"Invalid timeout_sec: {timeout_sec!r}")
        t_val = float(timeout_sec)
        if not math.isfinite(t_val) or t_val <= 0.0:
            raise ValueError(f"timeout_sec must be finite and > 0.0, got {timeout_sec!r}.")
        self.timeout_sec = t_val
        self._transport = transport or default_urllib_transport

    def __repr__(self) -> str:
        return (
            f"ElevenLabsAdapter(base_url={self.base_url!r}, "
            f"credential_source={self.credential_source()!r}, configured={self.is_configured()})"
        )

    def _resolve_raw_key(self) -> str:
        if self._credential_provider is not None:
            val = self._credential_provider()
            if val and str(val).strip():
                return str(val).strip()
        return os.environ.get(self.api_key_env, "").strip()

    def credential_source(self) -> str:
        if self.connector_authenticated:
            return "connector_transport"
        if self._credential_provider is not None:
            try:
                val = self._credential_provider()
                if val and str(val).strip():
                    return "credential_provider"
            except Exception:
                return "unconfigured"
        if os.environ.get(self.api_key_env, "").strip():
            return "environment"
        return "unconfigured"

    def _get_api_key(self) -> str:
        key = self._resolve_raw_key()
        if not key:
            raise ProviderAuthError(
                f"Missing ElevenLabs credentials: no connector auth, credential_provider, "
                f"or environment variable {self.api_key_env} is configured.",
                status_code=401,
                retryable=False,
            )
        return key

    def is_configured(self) -> bool:
        return self.credential_source() != "unconfigured"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_to_speech=True,
            voice_discovery=True,
            voice_design=True,
            authorized_voice_cloning=False,
            adjustable_controls=["stability", "similarity_boost", "style", "speed", "use_speaker_boost"],
            voice_design_controls=["loudness", "guidance_scale", "model_id"],
            quota_reporting=True,
            recorded_audio_import=False,
            verified_live=False,
        )

    def _headers(self, content_type: Optional[str] = "application/json", accept: str = "application/json") -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": accept}
        if not self.connector_authenticated:
            headers["xi-api-key"] = self._get_api_key()
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _raise_for_status(self, resp: HTTPResponseData, context: str) -> None:
        if 200 <= resp.status_code < 300:
            return
        detail = ""
        try:
            parsed = json.loads(resp.body.decode("utf-8", errors="replace"))
            detail = str(parsed.get("detail") or parsed.get("message") or parsed)
        except Exception:
            detail = resp.body.decode("utf-8", errors="replace")[:300]
        # Never echo secrets back in error text
        for candidate_key in (
            os.environ.get(self.api_key_env, "").strip(),
            self._resolve_raw_key() if not self.connector_authenticated else "",
        ):
            if candidate_key and candidate_key in detail:
                detail = detail.replace(candidate_key, "[REDACTED]")
        if resp.status_code in (401, 403):
            raise ProviderAuthError(
                f"ElevenLabs authentication failed during {context} (HTTP {resp.status_code}): {detail}",
                status_code=resp.status_code,
                retryable=False,
            )
        if resp.status_code == 404:
            raise ProviderVoiceNotFoundError(
                f"ElevenLabs resource or voice ID not found during {context} (HTTP 404): {detail}",
                status_code=404,
                retryable=False,
            )
        if resp.status_code in (402, 429) or "quota" in detail.lower() or "credit" in detail.lower():
            raise ProviderQuotaError(
                f"ElevenLabs quota or rate limit exceeded during {context} (HTTP {resp.status_code}): {detail}",
                status_code=resp.status_code,
                retryable=(resp.status_code == 429),
            )
        retryable = resp.status_code >= 500
        raise VoiceProviderError(
            f"ElevenLabs request failed during {context} (HTTP {resp.status_code}): {detail}",
            status_code=resp.status_code,
            retryable=retryable,
        )

    def _parse_json_response(self, resp: HTTPResponseData, context: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(resp.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderResponseError(
                f"ElevenLabs returned malformed JSON during {context}: {exc}",
                status_code=resp.status_code,
                retryable=True,
            ) from exc
        if not isinstance(parsed, dict):
            raise ProviderResponseError(
                f"ElevenLabs returned unexpected JSON type ({type(parsed).__name__}) during {context}.",
                status_code=resp.status_code,
                retryable=True,
            )
        return parsed

    def check_authentication(self) -> Dict[str, Any]:
        resp = self._transport(
            "GET",
            f"{self.base_url}/user",
            self._headers(content_type=None),
            None,
            self.timeout_sec,
        )
        self._raise_for_status(resp, "authentication check")
        data = self._parse_json_response(resp, "authentication check")
        sub = data.get("subscription", {})
        return {
            "authenticated": True,
            "provider": self.provider_id,
            "tier": sub.get("tier", "unknown"),
            "character_count": sub.get("character_count"),
            "character_limit": sub.get("character_limit"),
        }

    def get_quota(self) -> Dict[str, Any]:
        resp = self._transport(
            "GET",
            f"{self.base_url}/user/subscription",
            self._headers(content_type=None),
            None,
            self.timeout_sec,
        )
        self._raise_for_status(resp, "quota check")
        data = self._parse_json_response(resp, "quota check")
        used = data.get("character_count", 0)
        limit = data.get("character_limit", 0)
        return {
            "provider": self.provider_id,
            "tier": data.get("tier", "unknown"),
            "character_count": used,
            "character_limit": limit,
            "characters_remaining": max(0, int(limit) - int(used)) if isinstance(limit, int) and isinstance(used, int) else None,
        }

    def list_voices(self) -> List[Dict[str, Any]]:
        resp = self._transport(
            "GET",
            f"{self.base_url}/voices",
            self._headers(content_type=None),
            None,
            self.timeout_sec,
        )
        self._raise_for_status(resp, "list voices")
        data = self._parse_json_response(resp, "list voices")
        voices = []
        for item in data.get("voices", []):
            voices.append(
                {
                    "provider_voice_id": item.get("voice_id"),
                    "name": item.get("name"),
                    "category": item.get("category", "unknown"),
                    "labels": item.get("labels", {}),
                }
            )
        return voices

    def synthesize_speech(self, request: SynthesisRequest) -> SynthesisResult:
        if not request.provider_voice_id or not request.provider_voice_id.strip():
            raise ProviderVoiceNotFoundError("provider_voice_id is required for synthesis.", status_code=400)
        if not request.text or not request.text.strip():
            raise ValueError("Dialogue text must be non-empty.")

        voice_id_q = urllib.parse.quote(request.provider_voice_id.strip(), safe="")
        fmt_q = urllib.parse.quote(request.output_format, safe="")
        url = f"{self.base_url}/text-to-speech/{voice_id_q}?output_format={fmt_q}"

        payload: Dict[str, Any] = {
            "text": request.text,
            "model_id": request.model_id or self.DEFAULT_MODEL_ID,
        }
        if request.voice_settings:
            allowed = {"stability", "similarity_boost", "style", "speed", "use_speaker_boost"}
            filtered = {k: v for k, v in request.voice_settings.items() if k in allowed}
            if filtered:
                payload["voice_settings"] = filtered

        resp = self._transport(
            "POST",
            url,
            self._headers(content_type="application/json", accept="audio/*"),
            json.dumps(payload).encode("utf-8"),
            self.timeout_sec,
        )
        self._raise_for_status(resp, f"text-to-speech ({request.provider_voice_id})")

        if not resp.body:
            raise ProviderResponseError(
                "ElevenLabs returned an empty audio response body.",
                status_code=resp.status_code,
                retryable=True,
            )

        out_path = Path(request.output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(resp.body)
        return SynthesisResult(
            provider=self.provider_id,
            provider_voice_id=request.provider_voice_id,
            output_path=out_path,
            bytes_written=len(resp.body),
            content_type=resp.headers.get("content-type", "audio/mpeg"),
            metadata={"model_id": payload["model_id"], "output_format": request.output_format},
        )

    def design_voice(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """Create a synthetic voice preview and save it via current ElevenLabs Voice Design routes.

        Uses:
          - POST /v1/text-to-voice/design (generate voice previews)
          - POST /v1/text-to-voice        (persist selected preview as a reusable voice)
        """
        voice_description = str(spec.get("voice_description", "")).strip()
        sample_text = str(spec.get("sample_text", "")).strip()
        if not (20 <= len(voice_description) <= 1000):
            raise ValueError("ElevenLabs voice_description must be between 20 and 1000 characters.")

        payload: Dict[str, Any] = {
            "voice_description": voice_description,
            "model_id": str(spec.get("model_id") or "eleven_multilingual_ttv_v2"),
        }
        if 100 <= len(sample_text) <= 1000:
            payload["text"] = sample_text
            payload["auto_generate_text"] = False
        elif len(sample_text) > 1000:
            raise ValueError("ElevenLabs sample_text must not exceed 1000 characters.")
        else:
            # ElevenLabs /v1/text-to-voice/design requires 100-1000 chars for `text` or `auto_generate_text=True`
            payload["auto_generate_text"] = True

        if spec.get("loudness") is not None:
            payload["loudness"] = spec["loudness"]
        if spec.get("guidance_scale") is not None:
            payload["guidance_scale"] = spec["guidance_scale"]

        resp = self._transport(
            "POST",
            f"{self.base_url}/text-to-voice/design",
            self._headers(content_type="application/json"),
            json.dumps(payload).encode("utf-8"),
            self.timeout_sec,
        )
        self._raise_for_status(resp, "voice design preview")
        data = self._parse_json_response(resp, "voice design preview")
        previews = data.get("previews", [])
        if not previews:
            raise ProviderResponseError("ElevenLabs voice design returned no previews.")
        selected = previews[0]
        generated_voice_id = selected.get("generated_voice_id")
        if not generated_voice_id:
            raise ProviderResponseError("ElevenLabs voice design preview missing generated_voice_id.")

        create_payload = {
            "voice_name": str(spec.get("display_name") or "Designed Voice"),
            "voice_description": voice_description,
            "generated_voice_id": generated_voice_id,
        }
        create_resp = self._transport(
            "POST",
            f"{self.base_url}/text-to-voice",
            self._headers(content_type="application/json"),
            json.dumps(create_payload).encode("utf-8"),
            self.timeout_sec,
        )
        self._raise_for_status(create_resp, "voice design save")
        saved = self._parse_json_response(create_resp, "voice design save")
        provider_voice_id = saved.get("voice_id") or generated_voice_id
        return {
            "provider": self.provider_id,
            "provider_voice_id": provider_voice_id,
            "generated_voice_id": generated_voice_id,
            "preview_count": len(previews),
        }

    def _build_clone_multipart_body(
        self,
        *,
        name: str,
        description: str,
        sample_paths: List[Path],
        labels: Optional[Dict[str, str]] = None,
    ) -> Tuple[str, bytes]:
        """Build sanitized multipart/form-data payload (retained for offline formatting tests only)."""
        if not sample_paths:
            raise ValueError("At least one validated audio sample is required for cloning.")

        boundary = f"----RobloxTownVoiceBoundary{uuid.uuid4().hex}"
        body_parts: List[bytes] = []

        def add_field(field_name: str, value: str) -> None:
            body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
            body_parts.append(
                f'Content-Disposition: form-data; name="{field_name}"\r\n\r\n{value}\r\n'.encode("utf-8")
            )

        add_field("name", name)
        add_field("description", description)
        if labels:
            add_field("labels", json.dumps(labels))

        for path in sample_paths:
            p = Path(path)
            mime_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            file_bytes = p.read_bytes()
            body_parts.append(f"--{boundary}\r\n".encode("utf-8"))
            body_parts.append(
                (
                    f'Content-Disposition: form-data; name="files[]"; filename="'
                    + p.name.replace("\\", "_").replace('"', "_").replace("\r", "_").replace("\n", "_")
                    + '"\r\n'
                    f"Content-Type: {mime_type}\r\n\r\n"
                ).encode("utf-8")
            )
            body_parts.append(file_bytes)
            body_parts.append(b"\r\n")

        body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        return boundary, b"".join(body_parts)

    def create_authorized_clone(
        self,
        *,
        name: str,
        description: str,
        sample_paths: List[Path],
        labels: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Unconditionally disabled at the provider-adapter boundary in v0.2.0 (D-RC6-01)."""
        _validate_clone_request_safety(name=name, description=description, labels=labels)
        raise ProhibitedVoiceCloningError(
            "Remote voice-cloning submission is unconditionally disabled at the provider-adapter "
            "boundary in v0.2.0 regardless of transport, connector authentication, or labels.",
            status_code=403,
            retryable=False,
        )

    def delete_voice(self, provider_voice_id: str) -> Dict[str, Any]:
        voice_id_q = urllib.parse.quote(provider_voice_id.strip(), safe="")
        resp = self._transport(
            "DELETE",
            f"{self.base_url}/voices/{voice_id_q}",
            self._headers(content_type=None),
            None,
            self.timeout_sec,
        )
        self._raise_for_status(resp, f"delete voice ({provider_voice_id})")
        return {"provider": self.provider_id, "provider_voice_id": provider_voice_id, "deleted": True}


class OpenAITTSAdapter(VoiceProviderAdapter):
    """Interchangeable adapter contract for OpenAI Audio Speech API.

    Declared for multi-provider compatibility; live API execution is not yet implemented.
    """

    provider_id = "openai_tts"
    display_name = "OpenAI TTS"

    def __init__(self, api_key_env: str = "OPENAI_API_KEY"):
        self.api_key_env = api_key_env

    def is_configured(self) -> bool:
        return bool(os.environ.get(self.api_key_env, "").strip())

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_to_speech=False,
            voice_discovery=False,
            voice_design=False,
            authorized_voice_cloning=False,
            adjustable_controls=[],
            quota_reporting=False,
            recorded_audio_import=False,
            implemented=False,
            verified_live=False,
        )

    def check_authentication(self) -> Dict[str, Any]:
        if not self.is_configured():
            raise ProviderAuthError(f"Environment variable {self.api_key_env} is not set.", status_code=401)
        raise ProviderCapabilityError("OpenAITTSAdapter live execution is not yet implemented.")

    def list_voices(self) -> List[Dict[str, Any]]:
        return [
            {"provider_voice_id": v, "name": v.title(), "category": "builtin"}
            for v in ("alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer")
        ]

    def synthesize_speech(self, request: SynthesisRequest) -> SynthesisResult:
        raise ProviderCapabilityError("OpenAITTSAdapter live TTS execution is not yet implemented.")


class GoogleCloudTTSAdapter(VoiceProviderAdapter):
    """Interchangeable adapter contract for Google Cloud Text-to-Speech.

    Declared for multi-provider compatibility; live API execution is not yet implemented.
    """

    provider_id = "google_cloud_tts"
    display_name = "Google Cloud TTS"

    def __init__(self, credentials_env: str = "GOOGLE_APPLICATION_CREDENTIALS"):
        self.credentials_env = credentials_env

    def is_configured(self) -> bool:
        return bool(os.environ.get(self.credentials_env, "").strip())

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_to_speech=False,
            voice_discovery=False,
            voice_design=False,
            authorized_voice_cloning=False,
            adjustable_controls=[],
            quota_reporting=False,
            recorded_audio_import=False,
            implemented=False,
            verified_live=False,
        )

    def check_authentication(self) -> Dict[str, Any]:
        if not self.is_configured():
            raise ProviderAuthError(f"Environment variable {self.credentials_env} is not set.", status_code=401)
        raise ProviderCapabilityError("GoogleCloudTTSAdapter live execution is not yet implemented.")

    def list_voices(self) -> List[Dict[str, Any]]:
        raise ProviderCapabilityError("GoogleCloudTTSAdapter live voice discovery is not yet implemented.")

    def synthesize_speech(self, request: SynthesisRequest) -> SynthesisResult:
        raise ProviderCapabilityError("GoogleCloudTTSAdapter live TTS execution is not yet implemented.")


class RecordedVoiceProviderAdapter(VoiceProviderAdapter):
    """Bridge adapter wrapping the verified local Recorded Voice Backend."""

    provider_id = "recorded_voice_backend"
    display_name = "Recorded Voice Backend (Local FFmpeg)"

    def is_configured(self) -> bool:
        return True

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            text_to_speech=False,
            voice_discovery=False,
            voice_design=False,
            authorized_voice_cloning=False,
            adjustable_controls=["trim", "volume_normalization", "sample_rate", "channels"],
            quota_reporting=False,
            recorded_audio_import=True,
            verified_live=True,
        )

    def check_authentication(self) -> Dict[str, Any]:
        return {"authenticated": True, "provider": self.provider_id, "mode": "local_recorded"}

    def list_voices(self) -> List[Dict[str, Any]]:
        return []

    def synthesize_speech(self, request: SynthesisRequest) -> SynthesisResult:
        raise ProviderCapabilityError(
            "RecordedVoiceProviderAdapter processes user-provided recordings and cannot synthesize TTS."
        )


class ProviderRegistry:
    """Manages registered voice providers and selects them by capability & configuration."""

    def __init__(self, adapters: Optional[List[VoiceProviderAdapter]] = None):
        self._adapters: Dict[str, VoiceProviderAdapter] = {}
        for adapter in adapters or [
            ElevenLabsAdapter(),
            OpenAITTSAdapter(),
            GoogleCloudTTSAdapter(),
            RecordedVoiceProviderAdapter(),
        ]:
            self.register(adapter)

    def register(self, adapter: VoiceProviderAdapter) -> None:
        self._adapters[adapter.provider_id] = adapter

    def get(self, provider_id: str) -> VoiceProviderAdapter:
        if provider_id not in self._adapters:
            raise KeyError(f"Unknown voice provider: {provider_id!r}")
        return self._adapters[provider_id]

    def list_providers(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for pid in sorted(self._adapters.keys()):
            adapter = self._adapters[pid]
            caps = adapter.capabilities()
            rows.append(
                {
                    "provider_id": pid,
                    "display_name": adapter.display_name,
                    "configured": adapter.is_configured(),
                    "credential_source": (
                        adapter.credential_source()
                        if hasattr(adapter, "credential_source")
                        else ("configured" if adapter.is_configured() else "unconfigured")
                    ),
                    "capabilities": caps.__dict__,
                }
            )
        return rows

    def select_provider(
        self,
        *,
        preferred_provider: Optional[str] = None,
        required_capability: str = "text_to_speech",
        require_configured: bool = True,
    ) -> VoiceProviderAdapter:
        def matches(adapter: VoiceProviderAdapter) -> Tuple[bool, str]:
            caps = adapter.capabilities()
            if not caps.implemented:
                return False, "is a contract stub (execution not implemented)"
            if not getattr(caps, required_capability, False):
                return False, f"does not support {required_capability}"
            if require_configured and not adapter.is_configured():
                return False, "is not configured (missing credentials)"
            return True, "ok"

        if preferred_provider:
            adapter = self.get(preferred_provider)
            ok, reason = matches(adapter)
            if not ok:
                raise ProviderCapabilityError(
                    f"Requested provider {preferred_provider!r} cannot be selected: {reason}."
                )
            return adapter

        for pid in ("elevenlabs", "openai_tts", "google_cloud_tts", "recorded_voice_backend"):
            adapter = self._adapters.get(pid)
            if adapter and matches(adapter)[0]:
                return adapter

        raise ProviderCapabilityError(
            f"No registered voice provider satisfies capability={required_capability!r} "
            f"(require_configured={require_configured})."
        )
