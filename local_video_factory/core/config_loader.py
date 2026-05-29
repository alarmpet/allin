"""config.yaml 로딩.

- 파일이 없거나 깨져도 기술 로그 대신 '쉬운 문장'으로 안내한다 (문서 08 원칙).
- 누락된 키는 안전한 기본값으로 자동 보정한다.
"""
from __future__ import annotations

import os
from typing import Any, Dict

try:
    import yaml
except ImportError:  # PyYAML 미설치 시 친절 안내
    yaml = None


class ConfigError(Exception):
    """설정을 읽을 수 없을 때. message는 사용자에게 그대로 보여줘도 되는 문장."""


# config.yaml이 일부 비어 있어도 동작하도록 하는 기본값
DEFAULTS: Dict[str, Any] = {
    "ollama_base_url": "http://localhost:11434",
    "ollama_chat_endpoint": "http://localhost:11434/api/chat",
    "ollama_model": "qwen3.5-9b-local:latest",
    "ollama_timeout": 180,
    "ollama_temperature": 0.2,
    "ollama_top_p": 0.9,
    "ollama_unload_after_run": False,
    "use_lmstudio": False,
    "use_gemma": False,
    "use_paid_api": False,
    "use_external_video_mcp": False,
    "default_max_shot_seconds": 6,
    "default_shot_seconds": 5,
    "default_frames_per_shot": 141,
    "default_fps": 24,
    "test_resolution": "512x320",
    "final_aspect_ratio": "9:16",
    "wan_gp_path": "C:/pinokio/api/wan.git/app",
    "wan_gp_output_path": "C:/pinokio/api/wan.git/app/outputs",
    "wan_gp_queue_template": "",
    "supertonic_home": "C:/Users/petbl/supertonic3-local-tts-20260517-r4",
    "supertonic_host": "127.0.0.1",
    "supertonic_port": 3093,
    "supertonic_model": "supertonic-3",
    "supertonic_lang": "ko",
    "supertonic_speed": 1.05,
    "supertonic_total_step": 8,
    "supertonic_silence_duration": 0.3,
    "supertonic_default_voice": "F1",
    "supertonic_path": "",
    "supertonic_voice_preset": "default_ko",
    "tts_output_format": "wav",
    "ffmpeg_path": "ffmpeg",
    "ffprobe_path": "ffprobe",
    "project_root": "./projects",
    "prompt_library_path": "./prompt_library",
    "ui_type": "gradio",
}


def default_config_path() -> str:
    """패키지 루트의 config.yaml 경로 (현재 작업 폴더와 무관하게 찾는다)."""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "config.yaml")


def _format_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return '"' + str(v).replace('"', '\\"') + '"'


def update_config_values(updates: Dict[str, Any], path: str | None = None) -> None:
    """config.yaml의 특정 스칼라 키만 갱신(주석/나머지 보존).

    기존 줄이 있으면 값만 교체하고, 없으면 파일 끝에 추가한다.
    중첩(들여쓴) 키나 리스트는 다루지 않는다 — 단순 최상위 스칼라 전용.
    """
    import re

    if path is None:
        path = default_config_path()
    if not os.path.exists(path):
        raise ConfigError(f"설정 파일을 찾지 못했어요: {path}")

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    remaining = dict(updates)
    for i, line in enumerate(lines):
        for key in list(remaining.keys()):
            # 최상위(들여쓰기 없음) 키만 매칭
            m = re.match(rf"^({re.escape(key)}):(\s*)([^#\n]*)(#.*)?$", line)
            if m:
                comment = m.group(4) or ""
                tail = ("  " + comment.strip()) if comment.strip() else ""
                lines[i] = f"{key}: {_format_value(remaining[key])}{tail}\n"
                del remaining[key]
                break

    if remaining:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append("\n# (진단/설정에서 추가됨)\n")
        for key, val in remaining.items():
            lines.append(f"{key}: {_format_value(val)}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def load_config(path: str | None = None) -> Dict[str, Any]:
    if path is None:
        path = default_config_path()

    if yaml is None:
        raise ConfigError(
            "설정을 읽는 데 필요한 PyYAML이 설치돼 있지 않아요.\n"
            "  해결: pip install -r requirements.txt"
        )

    if not os.path.exists(path):
        raise ConfigError(
            f"설정 파일을 찾지 못했어요: {path}\n"
            "  해결: 프로그램 폴더 안에 config.yaml이 있는지 확인해 주세요."
        )

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:  # type: ignore[union-attr]
        raise ConfigError(
            "config.yaml 형식이 조금 깨진 것 같아요.\n"
            "  해결: 들여쓰기/따옴표를 확인하거나 백업본으로 되돌려 주세요.\n"
            f"  (자세히: {e})"
        )

    if not isinstance(data, dict):
        raise ConfigError("config.yaml 내용이 올바른 설정 형식이 아니에요.")

    # 기본값 보정
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in data.items() if v is not None})

    # project_root 상대 경로를 config.yaml 기준 절대 경로로 보정
    if "project_root" in cfg and not os.path.isabs(cfg["project_root"]):
        config_dir = os.path.dirname(os.path.abspath(path))
        cfg["project_root"] = os.path.normpath(os.path.join(config_dir, cfg["project_root"]))

    # 금지 항목이 켜져 있으면 강제로 끄고 경고를 남긴다 (문서 규칙 보호)
    cfg["warnings"] = []
    for forbidden in ("use_lmstudio", "use_gemma", "use_paid_api", "use_external_video_mcp"):
        if cfg.get(forbidden):
            cfg[forbidden] = False
            cfg["warnings"].append(
                f"'{forbidden}'는 이 프로그램에서 사용할 수 없어 자동으로 꺼졌어요."
            )

    cfg["_config_path"] = path
    return cfg
