"""prompt_library_manager: 성공한 프롬프트를 라이브러리에 저장하고 재사용할 수 있게 관리한다."""
from __future__ import annotations

import json
import os
from typing import Any, Dict


def get_library_root() -> str:
    """config에 지정된 prompt_library_path 경로 사용. 로딩 실패 시 기본 상대 경로."""
    try:
        from . import config_loader
        cfg = config_loader.load_config()
        path = cfg.get("prompt_library_path")
        if path:
            if not os.path.isabs(path):
                here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                return os.path.abspath(os.path.join(here, path))
            return os.path.abspath(path)
    except Exception:
        pass
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(here, "prompt_library")


def ensure_library_dirs() -> str:
    root = get_library_root()
    for sub in ("characters", "styles", "success_cases"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    return root


def save_character_prompt(character_name: str, prompt: str) -> str:
    """특정 캐릭터 고정 프롬프트를 저장한다."""
    root = ensure_library_dirs()
    target = os.path.join(root, "characters", f"{character_name.lower()}.json")
    data = {
        "character_name": character_name,
        "prompt": prompt
    }
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return target


def save_style_prompt(style_name: str, prompt: str, negative: str = "") -> str:
    """특정 스타일 가이드 프롬프트를 저장한다."""
    root = ensure_library_dirs()
    target = os.path.join(root, "styles", f"{style_name.lower()}.json")
    data = {
        "style_name": style_name,
        "positive_prompt": prompt,
        "negative_prompt": negative
    }
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return target


def save_success_case(project_id: str, shot_number: int, data: Dict[str, Any]) -> str:
    """성공적인 생성 컷 프롬프트를 라이브러리에 백업한다."""
    root = ensure_library_dirs()
    filename = f"{project_id}_shot_{shot_number:03d}.json"
    target = os.path.join(root, "success_cases", filename)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return target


def list_characters() -> list[str]:
    root = ensure_library_dirs()
    folder = os.path.join(root, "characters")
    return [os.path.splitext(f)[0] for f in os.listdir(folder) if f.endswith(".json")]


def list_styles() -> list[str]:
    root = ensure_library_dirs()
    folder = os.path.join(root, "styles")
    return [os.path.splitext(f)[0] for f in os.listdir(folder) if f.endswith(".json")]


def list_success_cases() -> list[str]:
    root = ensure_library_dirs()
    folder = os.path.join(root, "success_cases")
    return [os.path.splitext(f)[0] for f in os.listdir(folder) if f.endswith(".json")]
