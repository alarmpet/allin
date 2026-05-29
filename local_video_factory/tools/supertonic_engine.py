"""Supertonic3 (로컬 TTS) 어댑터.

HTTP 서버가 떠 있으면 그쪽을(빠름), 없으면 venv CLI를 직접 실행한다(폴백).
이 프로그램과 Supertonic3 설치본을 느슨하게 연결한다 — 경로는 config.yaml에서 읽는다.

검증된 호출 규약(newauto 통합 기준):
  CLI:  <home>/supertonic3-local-tts/.venv-win/Scripts/python.exe
        <home>/supertonic3-local-tts/src/supertonic3_cli.py
        --input in.txt --output out.wav --model supertonic-3 --voice F1
        --lang ko --speed 1.05 --total-step 8 --silence-duration 0.3 --json
  HTTP: GET  {url}/health      -> {"ok": true}
        POST {url}/api/tts     {text, voice, model, lang, speed, total_step, silence_duration}
                               -> {"ok": true, "path": "...wav"}
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

DEFAULT_VOICES = ["M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5"]
_HEALTH_TIMEOUT = 2.0
_HTTP_TIMEOUT = 300.0


class TTSError(Exception):
    """TTS 실패. message는 사용자에게 보여줄 쉬운 문장."""


# ── 경로 helper ────────────────────────────────────────────────
def _paths(cfg: Dict[str, Any]) -> Tuple[Path, Path, Path]:
    home = Path(str(cfg.get("supertonic_home", ""))).expanduser()
    tts_dir = home / "supertonic3-local-tts"
    python_path = tts_dir / ".venv-win" / "Scripts" / "python.exe"
    cli_path = tts_dir / "src" / "supertonic3_cli.py"
    return tts_dir, python_path, cli_path


def _server_url(cfg: Dict[str, Any]) -> str:
    host = cfg.get("supertonic_host", "127.0.0.1")
    port = cfg.get("supertonic_port", 3093)
    return f"http://{host}:{port}"


def _http_get(url: str, timeout: float) -> Optional[dict]:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
        data = json.loads(body)
        return data if isinstance(data, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def _http_post(url: str, payload: dict, timeout: float) -> Optional[dict]:
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
        out = json.loads(body)
        return out if isinstance(out, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


# ── 상태 점검 ──────────────────────────────────────────────────
def probe(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Supertonic3 사용 가능 여부를 점검한다."""
    tts_dir, python_path, cli_path = _paths(cfg)
    url = _server_url(cfg)
    health = _http_get(f"{url}/health", _HEALTH_TIMEOUT)
    server_ok = bool(health and health.get("ok") is True)
    cli_ok = python_path.exists() and cli_path.exists()

    if server_ok:
        msg = "Supertonic3 음성 서버가 켜져 있어요 (빠른 모드)."
    elif cli_ok:
        msg = "Supertonic3를 직접 실행할 수 있어요 (CLI 모드)."
    else:
        msg = (f"Supertonic3를 찾지 못했어요. config.yaml의 supertonic_home을 확인해 주세요.\n"
               f"  확인 경로: {python_path}")

    return {
        "available": server_ok or cli_ok,
        "server_ok": server_ok,
        "cli_ok": cli_ok,
        "server_url": url if server_ok else "",
        "python_path": str(python_path) if cli_ok else "",
        "cli_path": str(cli_path) if cli_ok else "",
        "message": msg,
    }


def _profile(cfg: Dict[str, Any], voice: str) -> Dict[str, Any]:
    return {
        "model": cfg.get("supertonic_model", "supertonic-3"),
        "voice": voice or cfg.get("supertonic_default_voice", "F1"),
        "lang": cfg.get("supertonic_lang", "ko"),
        "speed": cfg.get("supertonic_speed", 1.05),
        "total_step": cfg.get("supertonic_total_step", 8),
        "silence_duration": cfg.get("supertonic_silence_duration", 0.3),
    }


def _wav_duration(path: Path) -> Tuple[float, int]:
    with wave.open(str(path), "rb") as w:
        rate = int(w.getframerate())
        frames = int(w.getnframes())
    if rate <= 0:
        raise TTSError("생성된 오디오 길이를 읽지 못했어요.")
    return round(frames / rate, 3), rate


# ── 합성 ───────────────────────────────────────────────────────
def synthesize(cfg: Dict[str, Any], text: str, output_path: str, *,
               voice: str = "", status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """문장 하나를 wav로 합성한다. 반환: {path, duration, sample_rate, invocation}."""
    text = (text or "").strip()
    if not text:
        raise TTSError("나레이션 문장이 비어 있어요.")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    profile = _profile(cfg, voice)
    st = status or probe(cfg)

    # 1) HTTP 우선
    if st.get("server_ok") and st.get("server_url"):
        payload = dict(profile)
        payload["text"] = text
        resp = _http_post(f"{st['server_url']}/api/tts", payload, _HTTP_TIMEOUT)
        if resp and resp.get("ok") and isinstance(resp.get("path"), str):
            src = Path(resp["path"])
            if src.exists():
                if src.resolve() != out.resolve():
                    shutil.copyfile(src, out)
                dur, rate = _wav_duration(out)
                return {"path": str(out), "duration": dur, "sample_rate": rate,
                        "invocation": "http", "voice": profile["voice"]}

    # 2) CLI 폴백
    if not st.get("cli_ok"):
        raise TTSError(st.get("message", "Supertonic3를 사용할 수 없어요."))

    with tempfile.TemporaryDirectory(prefix="lvf-tts-") as tmp:
        in_path = Path(tmp) / "input.txt"
        in_path.write_text(text, encoding="utf-8")
        cmd = [
            st["python_path"], st["cli_path"],
            "--input", str(in_path), "--output", str(out),
            "--model", str(profile["model"]), "--voice", str(profile["voice"]),
            "--lang", str(profile["lang"]), "--speed", str(profile["speed"]),
            "--total-step", str(profile["total_step"]),
            "--silence-duration", str(profile["silence_duration"]),
            "--json",
        ]
        completed = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise TTSError("나레이션 생성에 실패했어요. (Supertonic3 실행 오류)\n  " + detail[:300])
    if not out.exists():
        raise TTSError("Supertonic3가 오디오를 만들지 못했어요.")

    dur, rate = _wav_duration(out)
    return {"path": str(out), "duration": dur, "sample_rate": rate,
            "invocation": "cli", "voice": profile["voice"]}
