"""supertonic_tts_skill: 컷별 나레이션 → audio/audio_XXX.wav

문서 05/03:
- 컷별 TTS 생성, voice preset 매핑, audio_001.wav 저장, 길이 측정
- 실패 시 TTS 없이 진행 옵션 (개별 컷 실패는 건너뛰고 계속)

진행상황을 단계별로 yield 하는 제너레이터 — Gradio 진행률과 CLI 양쪽에서 쓴다.
마지막 yield는 ("done", summary).
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, Tuple

from tools import supertonic_engine


def synthesize_all(cfg: Dict[str, Any], pm, project: Dict[str, Any],
                   shots_data: Dict[str, Any], voice: str = "") -> Iterator[Tuple]:
    """모든 컷의 나레이션을 만든다.

    yields:
      ("progress", i, total, shot_number)
      ("shot_done", shot_number, duration, ok)
      ("done", summary)
    """
    shots = shots_data["shots"]
    total = len(shots)

    status = supertonic_engine.probe(cfg)
    if not status["available"]:
        yield ("done", {"ok": False, "generated": 0, "failed": total,
                        "message": status["message"], "engine": status})
        return

    log_path = pm.path("logs", "tts.log")
    generated = 0
    failed = []
    for i, shot in enumerate(shots, start=1):
        num = shot["shot_number"]
        yield ("progress", i, total, num)
        text = (shot.get("tts_text") or "").strip()
        rel = shot.get("tts_file", f"audio/audio_{num:03d}.wav")
        out_path = pm.path(rel)
        if not text:
            shot["tts_status"] = "skipped"
            shot["tts_duration"] = 0.0
            failed.append(num)
            yield ("shot_done", num, 0.0, False)
            continue
        try:
            res = supertonic_engine.synthesize(cfg, text, out_path, voice=voice, status=status)
            shot["tts_file"] = rel
            shot["tts_duration"] = res["duration"]
            shot["tts_voice"] = res["voice"]
            shot["tts_status"] = "ready"
            generated += 1
            yield ("shot_done", num, res["duration"], True)
        except supertonic_engine.TTSError as e:
            shot["tts_status"] = "failed"
            shot["tts_duration"] = 0.0
            failed.append(num)
            _log(log_path, f"shot {num} 실패: {e}")
            yield ("shot_done", num, 0.0, False)

    # shots.json 갱신
    pm.save_json("shots.json", shots_data)

    summary = {
        "ok": generated > 0,
        "generated": generated,
        "failed_shots": failed,
        "failed": len(failed),
        "total": total,
        "voice": voice or cfg.get("supertonic_default_voice", "F1"),
        "engine": status,
        "message": (f"나레이션 {generated}/{total}개를 만들었어요." if generated else
                    "나레이션을 하나도 만들지 못했어요."),
    }
    yield ("done", summary)


def _log(path: str, msg: str) -> None:
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:  # noqa: BLE001
        pass
