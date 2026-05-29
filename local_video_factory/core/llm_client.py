"""Ollama (Qwen3.5 9B) 호출 전용 모듈.

문서 03/05 준수:
- /api/chat, stream=false
- 마크다운 코드블록 제거 후 JSON 추출
- 실패 시 '쉬운 문장' 에러 (문서 08)
- 필요 시 keep_alive:0 으로 모델 unload (영상 생성 전 VRAM 확보)

성능/안정성 개선:
- format="json" 옵션으로 Qwen이 유효 JSON만 내도록 강제 → 파싱 실패율 감소
- 서버/모델 사전 점검 함수 제공 (환경 점검 화면 재사용)
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import requests

from . import validate_json


class LLMError(Exception):
    """LLM 호출 실패. message는 사용자에게 보여줄 쉬운 문장.
    code로 어떤 해결 버튼을 띄울지 구분한다."""

    def __init__(self, message: str, code: str = "unknown", detail: str = ""):
        super().__init__(message)
        self.message = message
        self.code = code      # server_down | model_missing | timeout | bad_json | unknown
        self.detail = detail  # 로그용 원본


def check_server(cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """Ollama 서버가 떠 있는지 확인."""
    try:
        r = requests.get(f"{cfg['ollama_base_url']}/api/tags", timeout=5)
        r.raise_for_status()
        return True, "Ollama가 실행 중이에요."
    except requests.exceptions.ConnectionError:
        return False, "Qwen 두뇌(Ollama)와 연결이 안 됐어요. Ollama가 켜져 있는지 확인해 주세요."
    except Exception as e:  # noqa: BLE001
        return False, f"Ollama 상태를 확인하지 못했어요. (자세히: {e})"


def list_models(cfg: Dict[str, Any]) -> List[str]:
    """설치된 모델 목록."""
    try:
        r = requests.get(f"{cfg['ollama_base_url']}/api/tags", timeout=5)
        r.raise_for_status()
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:  # noqa: BLE001
        return []


def ensure_model(cfg: Dict[str, Any]) -> Tuple[bool, str, List[str]]:
    """config에 지정된 모델이 실제 설치돼 있는지 확인.

    반환: (정상여부, 메시지, 설치된_모델_목록)
    """
    model = cfg["ollama_model"]
    available = list_models(cfg)
    if not available:
        return False, "설치된 모델 목록을 가져오지 못했어요. Ollama 연결을 먼저 확인해 주세요.", []

    # 정확히 일치하거나, 태그(:latest)를 빼고 일치하면 통과
    base = model.split(":")[0]
    for name in available:
        if name == model or name.split(":")[0] == base:
            return True, f"모델 '{name}'을(를) 사용할게요.", available

    return (
        False,
        f"설정된 Qwen 모델 '{model}'을(를) 찾지 못했어요.\n"
        f"  설치된 모델: {', '.join(available)}",
        available,
    )


def chat(cfg: Dict[str, Any], system_prompt: str, user_content: str,
         *, force_json: bool = True, log_path: str | None = None) -> str:
    """Ollama /api/chat 호출 후 코드블록을 제거한 본문 텍스트를 반환."""
    payload: Dict[str, Any] = {
        "model": cfg["ollama_model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "stream": False,
        "options": {
            "temperature": cfg.get("ollama_temperature", 0.2),
            "top_p": cfg.get("ollama_top_p", 0.9),
        },
    }
    if force_json:
        payload["format"] = "json"  # Qwen이 유효 JSON만 출력하도록 강제

    try:
        resp = requests.post(
            cfg["ollama_chat_endpoint"], json=payload,
            timeout=cfg.get("ollama_timeout", 180),
        )
    except requests.exceptions.ConnectionError as e:
        raise LLMError(
            "Qwen 두뇌(Ollama)와 연결이 안 됐어요. Ollama가 켜져 있는지 확인해 주세요.",
            code="server_down", detail=str(e),
        )
    except requests.exceptions.Timeout as e:
        raise LLMError(
            "AI 응답이 너무 오래 걸려요. 대본을 조금 줄이거나 잠시 후 다시 시도해 주세요.",
            code="timeout", detail=str(e),
        )

    if resp.status_code == 404:
        raise LLMError(
            f"설정된 Qwen 모델 '{cfg['ollama_model']}'을(를) 찾지 못했어요. "
            "config.yaml의 ollama_model을 확인해 주세요.",
            code="model_missing", detail=resp.text,
        )
    try:
        resp.raise_for_status()
        content = resp.json()["message"]["content"]
    except Exception as e:  # noqa: BLE001
        raise LLMError(
            "AI 응답을 받지 못했어요. 잠시 후 다시 시도해 주세요.",
            code="unknown", detail=f"{e} / {resp.text[:500]}",
        )

    if log_path:
        _append_log(log_path, system_prompt, user_content, content)

    return validate_json.strip_code_fences(content)


def chat_json(cfg: Dict[str, Any], system_prompt: str, user_content: str,
              *, log_path: str | None = None) -> Any:
    """chat() 결과를 JSON으로 파싱(복구 포함)해서 반환."""
    text = chat(cfg, system_prompt, user_content, force_json=True, log_path=log_path)
    try:
        return validate_json.loads_with_repair(text)
    except validate_json.JSONRepairError as e:
        raise LLMError(str(e), code="bad_json", detail=text[:1000])


def unload_model(cfg: Dict[str, Any]) -> bool:
    """영상 생성 전 VRAM 확보를 위해 모델을 메모리에서 내린다."""
    try:
        requests.post(
            f"{cfg['ollama_base_url']}/api/generate",
            json={"model": cfg["ollama_model"], "keep_alive": 0},
            timeout=30,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def _append_log(log_path: str, system_prompt: str, user_content: str, response: str) -> None:
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n===== OLLAMA CALL =====\n")
            f.write("[SYSTEM]\n" + system_prompt[:2000] + "\n")
            f.write("[USER]\n" + user_content[:2000] + "\n")
            f.write("[RESPONSE]\n" + response[:4000] + "\n")
    except Exception:  # noqa: BLE001
        pass  # 로그 실패가 본 작업을 막으면 안 됨
