#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import mimetypes
import os
import socket
import subprocess
import sys
import tempfile
import uuid
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse


DEFAULT_IMAGE_ONLY_PROMPT = (
    "Edit the supplied image conservatively while preserving the main subject, "
    "overall composition, and recognizable details."
)
SKILL_NAME = "Codex Image Workbench"
PREVIEW_HOST = "127.0.0.1"
PREVIEW_PORT = 48551


@dataclass
class ResolvedConfig:
    base_url: str
    model: str
    api_key: str
    api_key_source: str
    api_key_kind: str
    config_root: str
    wire_api: str | None
    provider_name: str | None
    auth_path: str | None
    config_path: str | None
    skill_config_path: str | None
    raw_base_url: str | None
    request_mode: str | None

    def sanitized(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "raw_base_url": self.raw_base_url,
            "model": self.model,
            "api_key_present": bool(self.api_key),
            "api_key_source": self.api_key_source,
            "api_key_kind": self.api_key_kind,
            "config_root": self.config_root,
            "wire_api": self.wire_api,
            "provider_name": self.provider_name,
            "auth_path": self.auth_path,
            "config_path": self.config_path,
            "skill_config_path": self.skill_config_path,
            "request_mode": self.request_mode,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or edit images by reusing the current Codex configuration."
    )
    parser.add_argument("--prompt", help="Prompt or edit instruction.")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        help="Local image path. Repeat to attach multiple images.",
    )
    parser.add_argument(
        "--previous-response-id",
        help="Continue an earlier Responses API image iteration.",
    )
    parser.add_argument("--base-url", help="Override the resolved API base URL.")
    parser.add_argument("--api-key", help="Override the resolved API key.")
    parser.add_argument("--model", help="Override the resolved mainline model.")
    parser.add_argument(
        "--config-file",
        help="Skill-local config file. Defaults to image-provider.toml next to the skill.",
    )
    parser.add_argument(
        "--config-root",
        help="Codex home directory. Defaults to CODEX_HOME or ~/.codex.",
    )
    parser.add_argument(
        "--output-dir",
        default="codex-image-output",
        help="Directory used for generated images and metadata.",
    )
    parser.add_argument(
        "--ephemeral",
        action="store_true",
        help="Write outputs into the system temp directory for preview-oriented runs.",
    )
    parser.add_argument(
        "--skip-metadata",
        action="store_true",
        help="Do not write the metadata JSON file.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Open a Python preview window after successful generation.",
    )
    parser.add_argument(
        "--preview-title",
        default=SKILL_NAME,
        help="Title for the optional preview window.",
    )
    parser.add_argument(
        "--output-prefix",
        help="Prefix for generated filenames. Defaults to a timestamp.",
    )
    parser.add_argument(
        "--size",
        default="1024x1024",
        help="Image size such as 1024x1024, 1536x1024, 1024x1536, or auto.",
    )
    parser.add_argument(
        "--quality",
        default="auto",
        choices=["auto", "low", "medium", "high"],
        help="Generation quality.",
    )
    parser.add_argument(
        "--background",
        default="auto",
        choices=["auto", "transparent", "opaque"],
        help="Background setting for supported formats.",
    )
    parser.add_argument(
        "--format",
        default="png",
        choices=["png", "jpeg", "webp"],
        help="Output image format.",
    )
    parser.add_argument(
        "--compression",
        type=int,
        help="Output compression 0-100 for jpeg/webp.",
    )
    parser.add_argument(
        "--moderation",
        choices=["auto", "low"],
        help="Moderation level.",
    )
    parser.add_argument(
        "--input-fidelity",
        choices=["low", "high"],
        help="Input image fidelity when editing based on local images.",
    )
    parser.add_argument(
        "--action",
        choices=["auto", "generate", "edit"],
        help="Optional tool action for providers that expose GPT Image action control.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve configuration and payload without sending a request.",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Probe the configured endpoint for likely image-capable models.",
    )
    parser.add_argument(
        "--probe-model",
        action="append",
        default=[],
        help="Candidate model to test during --probe. Repeatable.",
    )
    return parser.parse_args()


def default_config_root(explicit_root: str | None) -> Path:
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()
    env_root = os.environ.get("CODEX_HOME")
    if env_root:
        return Path(env_root).expanduser().resolve()
    return (Path.home() / ".codex").resolve()


def load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_skill_config_path(explicit_path: str | None) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    return skill_root() / "image-provider.toml"


def normalize_base_url(value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        return raw
    parsed = urlparse(raw)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        return raw
    if path.endswith("/responses") or path.endswith("/images") or path.endswith("/models"):
        return raw
    new_path = f"{path}/v1" if path else "/v1"
    return urlunparse(parsed._replace(path=new_path))


def is_gpt_image_model(model: str) -> bool:
    return model.startswith("gpt-image-") or model == "chatgpt-image-latest"


def load_skill_config(path: Path) -> dict[str, Any]:
    return load_toml(path)


def nested_get(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def resolve_config(args: argparse.Namespace) -> ResolvedConfig:
    config_root = default_config_root(args.config_root)
    config_path = config_root / "config.toml"
    auth_path = config_root / "auth.json"
    skill_config_path = default_skill_config_path(args.config_file)
    config = load_toml(config_path)
    auth = load_json(auth_path)
    skill_config = load_skill_config(skill_config_path)

    provider_name = config.get("model_provider")
    providers = config.get("model_providers", {})
    provider_config = providers.get(provider_name, {}) if isinstance(providers, dict) else {}

    explicit_base_url = args.base_url or os.environ.get("CODEX_IMAGE_BASE_URL")
    explicit_model = args.model or os.environ.get("CODEX_IMAGE_MODEL")
    explicit_key = args.api_key or os.environ.get("CODEX_IMAGE_API_KEY")

    skill_base_url = nested_get(skill_config, "provider", "base_url")
    skill_model = nested_get(skill_config, "provider", "model")
    skill_key = nested_get(skill_config, "provider", "api_key")
    skill_wire_api = nested_get(skill_config, "provider", "wire_api")

    auth_key = auth.get("OPENAI_API_KEY")
    env_key = os.environ.get("OPENAI_API_KEY")

    api_key = explicit_key or skill_key or auth_key or env_key or ""
    if explicit_key:
        api_key_source = "override"
    elif skill_key:
        api_key_source = "skill_config"
    elif auth_key:
        api_key_source = "auth.json"
    elif env_key:
        api_key_source = "OPENAI_API_KEY"
    else:
        api_key_source = "missing"

    if api_key == "PROXY_MANAGED":
        api_key_kind = "proxy-managed"
    elif api_key:
        api_key_kind = "literal"
    else:
        api_key_kind = "missing"

    raw_base_url = explicit_base_url or skill_base_url or provider_config.get("base_url") or ""
    base_url = normalize_base_url(raw_base_url)
    model = explicit_model or skill_model or config.get("model") or "gpt-image-1"
    wire_api = skill_wire_api or provider_config.get("wire_api")

    if not base_url:
        raise ValueError(
            f"Unable to resolve base_url from {config_path}. "
            "Pass --base-url, set CODEX_IMAGE_BASE_URL, or update the skill config."
        )
    if not api_key:
        raise ValueError(
            "Unable to resolve an API key. Pass --api-key or set "
            "CODEX_IMAGE_API_KEY / OPENAI_API_KEY, or update the skill config."
        )

    return ResolvedConfig(
        base_url=base_url.rstrip("/"),
        model=model,
        api_key=api_key,
        api_key_source=api_key_source,
        api_key_kind=api_key_kind,
        config_root=str(config_root),
        wire_api=wire_api,
        provider_name=provider_name,
        auth_path=str(auth_path) if auth_path.exists() else None,
        config_path=str(config_path) if config_path.exists() else None,
        skill_config_path=str(skill_config_path) if skill_config_path.exists() else str(skill_config_path),
        raw_base_url=raw_base_url or None,
        request_mode="images" if is_gpt_image_model(model) else "responses",
    )


def encode_image(path_value: str) -> dict[str, str]:
    path = Path(path_value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type:
        mime_type = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "input_image",
        "image_url": f"data:{mime_type};base64,{encoded}",
    }


def build_payload(args: argparse.Namespace, config: ResolvedConfig) -> dict[str, Any]:
    prompt = args.prompt
    images = [encode_image(item) for item in args.image]
    if not prompt and images:
        prompt = DEFAULT_IMAGE_ONLY_PROMPT
    if not prompt and not args.previous_response_id:
        raise ValueError("Provide --prompt, --image, or --previous-response-id.")

    content: list[dict[str, Any]] = []
    if prompt:
        content.append({"type": "input_text", "text": prompt})
    content.extend(images)

    tool: dict[str, Any] = {
        "type": "image_generation",
        "size": args.size,
        "quality": args.quality,
        "background": args.background,
        "output_format": args.format,
    }
    if args.compression is not None:
        tool["output_compression"] = args.compression
    if args.moderation:
        tool["moderation"] = args.moderation
    if args.input_fidelity:
        tool["input_fidelity"] = args.input_fidelity
    if args.action:
        tool["action"] = args.action

    payload: dict[str, Any] = {
        "model": config.model,
        "tools": [tool],
        "tool_choice": {"type": "image_generation"},
        "store": False,
    }
    if content:
        payload["input"] = [{"role": "user", "content": content}]
    if args.previous_response_id:
        payload["previous_response_id"] = args.previous_response_id
    return payload


def ensure_output_dir(path_value: str) -> Path:
    output_dir = Path(path_value).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def effective_output_dir(args: argparse.Namespace) -> Path:
    if args.ephemeral:
        return ensure_output_dir(str(Path(tempfile.gettempdir()) / "codex-image-workbench"))
    return ensure_output_dir(args.output_dir)


def request_json(url: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Codex/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read().decode("utf-8"))


def request_multipart(
    url: str,
    api_key: str,
    fields: list[tuple[str, str]],
    files: list[tuple[str, Path]],
) -> dict[str, Any]:
    boundary = f"----CodexImageBoundary{uuid.uuid4().hex}"
    body = bytearray()

    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        body.extend(value.encode("utf-8"))
        body.extend(b"\r\n")

    for name, path in files:
        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{path.name}"\r\n'
            ).encode("utf-8")
        )
        body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
        body.extend(path.read_bytes())
        body.extend(b"\r\n")

    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    request = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "Codex/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read().decode("utf-8"))


def build_image_api_payload(
    args: argparse.Namespace,
    config: ResolvedConfig,
) -> tuple[str, dict[str, Any] | None, list[tuple[str, str]] | None, list[tuple[str, Path]] | None]:
    if args.previous_response_id:
        raise ValueError(
            "The current provider is configured to use the Images API for GPT Image models, "
            "so --previous-response-id is not supported."
        )

    prompt = args.prompt
    image_paths = [Path(item).expanduser().resolve() for item in args.image]
    if not prompt and image_paths:
        prompt = DEFAULT_IMAGE_ONLY_PROMPT
    if not prompt:
        raise ValueError("Provide --prompt or --image.")

    common_fields: dict[str, Any] = {
        "model": config.model,
        "size": args.size,
        "quality": args.quality,
        "background": args.background,
        "output_format": args.format,
    }
    if args.compression is not None:
        common_fields["output_compression"] = args.compression
    if args.moderation:
        common_fields["moderation"] = args.moderation
    if args.input_fidelity:
        common_fields["input_fidelity"] = args.input_fidelity

    if image_paths:
        fields: list[tuple[str, str]] = [("model", config.model), ("prompt", prompt)]
        for key, value in common_fields.items():
            if key == "model" or value in (None, "", "auto"):
                continue
            fields.append((key, str(value)))
        files = [("image[]", path) for path in image_paths]
        return ("images_edits", None, fields, files)

    payload = {"prompt": prompt, **common_fields}
    return ("images_generations", payload, None, None)


def request_image_api(
    args: argparse.Namespace,
    config: ResolvedConfig,
) -> tuple[dict[str, Any], str]:
    request_kind, payload, fields, files = build_image_api_payload(args, config)
    if request_kind == "images_edits":
        response = request_multipart(
            f"{config.base_url}/images/edits",
            config.api_key,
            fields or [],
            files or [],
        )
        return response, "images/edits"

    response = request_json(
        f"{config.base_url}/images/generations",
        config.api_key,
        payload or {},
    )
    return response, "images/generations"


def probe_candidates_from_config(config: ResolvedConfig, args: argparse.Namespace) -> list[str]:
    skill_config_path = Path(config.skill_config_path) if config.skill_config_path else None
    skill_config = load_skill_config(skill_config_path) if skill_config_path and skill_config_path.exists() else {}
    configured = nested_get(skill_config, "detection", "candidate_models") or []
    candidates: list[str] = []
    for item in args.probe_model + configured + [config.model, "gpt-image-2", "gpt-image-1"]:
        if item and item not in candidates:
            candidates.append(item)
    return candidates


def probe_image_models(config: ResolvedConfig, args: argparse.Namespace) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for model in probe_candidates_from_config(config, args):
        payload = {
            "model": model,
            "input": "Generate a tiny simple red dot icon",
            "tools": [
                {
                    "type": "image_generation",
                    "quality": "low",
                    "size": "1024x1024",
                    "output_format": "png",
                }
            ],
            "tool_choice": {"type": "image_generation"},
            "store": False,
        }
        try:
            response = request_json(f"{config.base_url}/responses", config.api_key, payload)
            output_types = [item.get("type") for item in response.get("output", [])]
            has_image = any(
                item.get("type") == "image_generation_call" and item.get("result")
                for item in response.get("output", [])
            )
            attempt = {
                "model": model,
                "ok": True,
                "status": response.get("status"),
                "response_id": response.get("id"),
                "output_types": output_types,
                "has_image": has_image,
            }
            attempts.append(attempt)
            if has_image:
                return {
                    "ok": True,
                    "resolved_config": config.sanitized(),
                    "recommended_model": model,
                    "attempts": attempts,
                }
        except urllib.error.HTTPError as exc:
            attempts.append(
                {
                    "model": model,
                    "ok": False,
                    "status_code": exc.code,
                    "details": exc.read().decode("utf-8", errors="replace"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            attempts.append(
                {
                    "model": model,
                    "ok": False,
                    "error": str(exc),
                }
            )
    return {
        "ok": False,
        "resolved_config": config.sanitized(),
        "recommended_model": None,
        "attempts": attempts,
    }


def output_extension(image_format: str) -> str:
    if image_format == "jpeg":
        return "jpg"
    return image_format


def extract_text_output(payload: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                text = content.get("text", "").strip()
                if text:
                    texts.append(text)
    return texts


def save_outputs(
    args: argparse.Namespace,
    config: ResolvedConfig,
    payload: dict[str, Any] | None,
    response: dict[str, Any],
    endpoint_used: str,
) -> dict[str, Any]:
    output_dir = effective_output_dir(args)
    prefix = args.output_prefix or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    extension = output_extension(args.format)

    image_paths: list[str] = []
    revised_prompts: list[str] = []
    if endpoint_used.startswith("images/"):
        for index, item in enumerate(response.get("data", []), start=1):
            image_data = item.get("b64_json")
            if not image_data:
                continue
            image_path = output_dir / f"{prefix}-{index:02d}.{extension}"
            image_path.write_bytes(base64.b64decode(image_data))
            image_paths.append(str(image_path))
            revised_prompt = item.get("revised_prompt")
            if revised_prompt:
                revised_prompts.append(revised_prompt)
    else:
        for index, item in enumerate(response.get("output", []), start=1):
            if item.get("type") != "image_generation_call":
                continue
            image_data = item.get("result")
            if not image_data:
                continue
            image_path = output_dir / f"{prefix}-{index:02d}.{extension}"
            image_path.write_bytes(base64.b64decode(image_data))
            image_paths.append(str(image_path))
            revised_prompt = item.get("revised_prompt")
            if revised_prompt:
                revised_prompts.append(revised_prompt)

    metadata = {
        "ok": True,
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "resolved_config": config.sanitized(),
        "endpoint_used": endpoint_used,
        "request": {
            "prompt": args.prompt,
            "image_count": len(args.image),
            "previous_response_id": args.previous_response_id,
            "size": args.size,
            "quality": args.quality,
            "background": args.background,
            "format": args.format,
            "compression": args.compression,
            "moderation": args.moderation,
            "input_fidelity": args.input_fidelity,
            "action": args.action,
        },
        "response_id": response.get("id"),
        "status": response.get("status", "completed"),
        "image_paths": image_paths,
        "revised_prompts": revised_prompts,
        "text_output": extract_text_output(response) if endpoint_used == "responses" else [],
    }

    if not args.skip_metadata:
        metadata_path = output_dir / f"{prefix}-metadata.json"
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        metadata["metadata_path"] = str(metadata_path)
    return metadata


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def preview_payload(image_paths: list[str], title: str) -> dict[str, Any]:
    return {
        "title": title or SKILL_NAME,
        "images": image_paths,
        "updated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def send_preview_update(payload: dict[str, Any], timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((PREVIEW_HOST, PREVIEW_PORT), timeout=timeout) as client:
            client.sendall(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        return True
    except OSError:
        return False


def gui_python_executable() -> str:
    if os.name != "nt":
        return sys.executable
    executable = Path(sys.executable)
    if executable.name.lower() == "python.exe":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return sys.executable


def launch_preview_window(image_paths: list[str], title: str) -> None:
    if not image_paths:
        return
    payload = preview_payload(image_paths, title)
    if send_preview_update(payload):
        return
    preview_script = skill_root() / "scripts" / "image_preview_window.py"
    command = [gui_python_executable(), str(preview_script), "--title", title, *image_paths]
    if os.name == "nt":
        creationflags = 0
        create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        detached_process = getattr(subprocess, "DETACHED_PROCESS", 0)
        creationflags |= create_no_window | detached_process
        subprocess.Popen(command, creationflags=creationflags)
        return
    subprocess.Popen(command)


def main() -> int:
    args = parse_args()
    config: ResolvedConfig | None = None
    try:
        config = resolve_config(args)
        if args.probe:
            result = probe_image_models(config, args)
            print_json(result)
            return 0 if result.get("ok") else 1
        payload: dict[str, Any] | None
        endpoint_used: str
        if config.request_mode == "images":
            payload = None
            if args.dry_run:
                request_kind, preview_payload, preview_fields, preview_files = build_image_api_payload(
                    args, config
                )
                print_json(
                    {
                        "ok": True,
                        "dry_run": True,
                        "resolved_config": config.sanitized(),
                        "payload_preview": {
                            "request_kind": request_kind,
                            "json_payload": preview_payload,
                            "multipart_fields": preview_fields,
                            "multipart_file_count": len(preview_files or []),
                        },
                    }
                )
                return 0
            response, endpoint_used = request_image_api(args, config)
        else:
            payload = build_payload(args, config)
            endpoint_used = "responses"
        if args.dry_run:
            print_json(
                {
                    "ok": True,
                    "dry_run": True,
                    "resolved_config": config.sanitized(),
                    "payload_preview": {
                        "model": payload.get("model"),
                        "tool_choice": payload.get("tool_choice"),
                        "tools": payload.get("tools"),
                        "has_input": "input" in payload,
                        "has_previous_response_id": "previous_response_id" in payload,
                        "input_items": (
                            len(payload["input"][0]["content"])
                            if "input" in payload
                            else 0
                        ),
                    },
                }
            )
            return 0

        if config.request_mode != "images":
            response = request_json(
                f"{config.base_url}/responses",
                config.api_key,
                payload or {},
            )
        metadata = save_outputs(args, config, payload, response, endpoint_used)
        if args.preview:
            launch_preview_window(metadata.get("image_paths", []), args.preview_title)
        print_json(metadata)
        return 0
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        message = (
            "Image request failed. The current configured image provider rejected "
            "the request. Check the skill config, verify the endpoint supports "
            "image generation, or override CODEX_IMAGE_BASE_URL / "
            "CODEX_IMAGE_API_KEY / CODEX_IMAGE_MODEL."
        )
        error_payload = {
            "ok": False,
            "error_type": "http_error",
            "status_code": exc.code,
            "message": message,
            "details": body,
        }
        if config is not None:
            error_payload["resolved_config"] = config.sanitized()
        print_json(error_payload)
        return 1
    except Exception as exc:  # noqa: BLE001
        error_payload = {
            "ok": False,
            "error_type": "exception",
            "message": str(exc),
        }
        if config is not None:
            error_payload["resolved_config"] = config.sanitized()
        print_json(error_payload)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
