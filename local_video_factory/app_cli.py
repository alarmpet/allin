#!/usr/bin/env python3
"""Local Video Factory — Phase 1 CLI MVP

대본을 넣으면:
  projects/YYYY-MM-DD_제목/
    project.json, status.json,
    script_segments.json, shots.json,
    prompt_001.txt ..., negative_prompt.txt
가 생성된다. (Gradio UI 없이 터미널 전용)

사용 예:
  python app_cli.py check
  python app_cli.py make --title "비 오는 날 모찌" --mode mochi --duration 15 --script-file sample_script.txt
  echo "한 줄 아이디어" | python app_cli.py make --title "테스트" --mode emotional
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

# 어디서 실행하든 core/skills를 import할 수 있게
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Windows 콘솔에서 한글이 깨지지 않도록 표준 입출력을 UTF-8로 고정
for _stream in (sys.stdout, sys.stderr, sys.stdin):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass

from core import config_loader, llm_client, project_manager  # noqa: E402
from skills import (  # noqa: E402
    script_parser_skill,
    shot_planner_skill,
    prompt_director_skill,
)

MODE_CHOICES = ["emotional", "product_cf", "info", "mochi", "senior"]


# ── 출력 helper ────────────────────────────────────────────────
def say(msg: str) -> None:
    print(msg, flush=True)


def step(n: int, total: int, msg: str) -> None:
    print(f"  [{n}/{total}] {msg}", flush=True)


def fail(msg: str) -> None:
    print("\n[X] " + msg, flush=True)


# ── 환경 점검 (문서 08) ────────────────────────────────────────
def cmd_check(cfg) -> int:
    say("영상공장 가동 전 점검 중입니다.\n")
    ok = True

    # 1) Ollama 서버
    server_ok, server_msg = llm_client.check_server(cfg)
    say(("  [O] " if server_ok else "  [!] ") + server_msg)

    # 2) 모델 설치
    if server_ok:
        model_ok, model_msg, available = llm_client.ensure_model(cfg)
        say(("  [O] " if model_ok else "  [!] ") + model_msg)
        ok = ok and model_ok
    else:
        ok = False
        say("       (Ollama가 꺼져 있어 모델 확인을 건너뜁니다.)")

    # 3) projects 폴더 쓰기 가능
    root = os.path.abspath(cfg["project_root"])
    try:
        os.makedirs(root, exist_ok=True)
        testfile = os.path.join(root, ".write_test")
        with open(testfile, "w") as f:
            f.write("ok")
        os.remove(testfile)
        say(f"  [O] 프로젝트 폴더에 저장할 수 있어요: {root}")
    except Exception as e:  # noqa: BLE001
        ok = False
        say(f"  [!] 프로젝트 폴더에 쓸 수 없어요: {root} ({e})")

    # 4) 디스크 여유 공간
    try:
        free_gb = shutil.disk_usage(root).free / (1024 ** 3)
        mark = "[O]" if free_gb > 2 else "[!]"
        say(f"  {mark} 남은 디스크 공간: 약 {free_gb:.1f} GB")
    except Exception:  # noqa: BLE001
        pass

    # 5) ffmpeg / ffprobe (Phase 5에서 필요 — 지금은 정보용)
    for tool, key in (("ffmpeg", "ffmpeg_path"), ("ffprobe", "ffprobe_path")):
        found = shutil.which(cfg.get(key, tool))
        say((f"  [O] {tool} 준비됨" if found else
             f"  [i] {tool}는 아직 없어요 (Phase 5 최종 합성에서 필요)"))

    say("")
    if ok:
        say("[O] 핵심 점검 통과! 'make' 명령으로 대본을 넣어보세요.")
        return 0
    fail("일부 항목을 먼저 해결해 주세요. (위의 [!] 항목)")
    say("    - Ollama 실행:  ollama serve   (또는 Ollama 앱 실행)")
    say("    - 모델 확인:    ollama list")
    return 1


# ── 대본 → 컷 → 프롬프트 ──────────────────────────────────────
def _read_script(args) -> str:
    if args.script:
        return args.script
    if args.script_file:
        if not os.path.exists(args.script_file):
            raise FileNotFoundError(f"대본 파일을 찾지 못했어요: {args.script_file}")
        with open(args.script_file, "r", encoding="utf-8") as f:
            return f.read()
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        if data.strip():
            # PowerShell 5.1은 파이프로 보낼 때 한글을 '?'로 깨뜨릴 수 있다.
            q = data.count("?") + data.count("�")
            if q >= 3 and q > len(data) * 0.1:
                say("[알림] 입력된 대본에 깨진 글자가 많아요. "
                    "한글은 --script-file 또는 --script 사용을 권장합니다.")
            return data
    raise ValueError(
        "대본이 비어 있어요. --script \"...\" 또는 --script-file 경로 로 넣어주세요."
    )


def _parse_duration(value: str) -> int:
    if value is None or str(value).lower() in ("auto", "0", ""):
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


def cmd_make(cfg, args) -> int:
    # 0) 대본 확보
    try:
        script_text = _read_script(args).strip()
        if not script_text:
            raise ValueError("대본이 비어 있어요.")
    except (FileNotFoundError, ValueError) as e:
        fail(str(e))
        return 1

    # 1) Ollama 사전 점검 (친절 안내)
    server_ok, server_msg = llm_client.check_server(cfg)
    if not server_ok:
        fail(server_msg)
        say("    해결: Ollama를 실행한 뒤 다시 시도해 주세요 (ollama serve).")
        return 1
    model_ok, model_msg, _ = llm_client.ensure_model(cfg)
    if not model_ok:
        fail(model_msg)
        say("    해결: config.yaml의 ollama_model을 설치된 모델명으로 바꿔주세요.")
        return 1

    # 2) 프로젝트 폴더 생성
    mode = args.mode
    style = args.style or mode
    duration = _parse_duration(args.duration)
    pm = project_manager.create_project(
        cfg["project_root"], args.title,
        input_mode=mode, style_preset=style,
        target_duration=duration, cfg=cfg,
    )
    pm.save_text("script_original.txt", script_text)
    pm.save_text("idea.txt", script_text)
    project = pm.load_json("project.json")
    say(f"\n새 프로젝트: {pm.project_id}")
    say(f"  폴더: {pm.dir}\n")

    total = 3
    try:
        # 3) 대본 분석
        step(1, total, "대본을 분석하고 있어요...")
        pm.update_status("parsing_script")
        segments = script_parser_skill.parse_script(cfg, pm, project, script_text)
        n_seg = len(segments["segments"])
        pm.update_status("script_parsed")
        say(f"        → 문장 {n_seg}개 분석 완료")

        # 4) 컷 분해
        step(2, total, "장면을 6초 이하 컷으로 나누고 있어요...")
        pm.update_status("planning_shots")
        shots = shot_planner_skill.plan_shots(cfg, pm, project, segments)
        n_shots = len(shots["shots"])
        pm.update_status("shots_ready", total_shots=n_shots)
        say(f"        → 컷 {n_shots}개 생성 (예상 길이 약 {shots['target_duration']}초)")

        # 5) 프롬프트 생성
        step(3, total, "WanGP용 영상 프롬프트를 만들고 있어요...")
        pm.update_status("generating_prompts", total_shots=n_shots)
        prompt_director_skill.generate_prompts(cfg, pm, project, shots)
        pm.update_status("prompts_ready", total_shots=n_shots)
        say(f"        → prompt_001.txt ~ prompt_{n_shots:03d}.txt 저장 완료")

    except llm_client.LLMError as e:
        pm.update_status("failed", last_error=e.message)
        fail(e.message)
        if e.code == "bad_json":
            say("    해결: 같은 명령을 한 번 더 실행하면 대부분 정상 생성돼요.")
        _log_error(pm, e)
        return 1
    except Exception as e:  # noqa: BLE001
        pm.update_status("failed", last_error=str(e))
        fail(f"예상치 못한 문제가 생겼어요: {e}")
        _log_error(pm, e)
        return 1

    # 6) 영상 생성 전 VRAM 확보용 unload (선택)
    if cfg.get("ollama_unload_after_run"):
        llm_client.unload_model(cfg)

    _print_summary(pm)
    return 0


def _log_error(pm, e) -> None:
    try:
        with open(pm.path("logs", "error.log"), "a", encoding="utf-8") as f:
            detail = getattr(e, "detail", "") or repr(e)
            f.write(f"{type(e).__name__}: {detail}\n")
    except Exception:  # noqa: BLE001
        pass


def _print_summary(pm) -> None:
    say("\n" + "=" * 52)
    say("  완료! 컷 데이터와 프롬프트가 준비됐어요.")
    say("=" * 52)
    shots = pm.load_json("shots.json")["shots"]
    say(f"\n생성 위치: {pm.dir}\n")
    say("생성된 파일:")
    for name in ("project.json", "status.json", "script_segments.json", "shots.json",
                 "negative_prompt.txt"):
        if pm.exists(name):
            say(f"  - {name}")
    say(f"  - prompt_001.txt ~ prompt_{len(shots):03d}.txt")

    say("\n컷 미리보기:")
    for s in shots[:3]:
        say(f"\n  컷 {s['shot_number']:03d}  (약 {s['duration']}초, {s['status']})")
        say(f"    장면: {s['korean_description']}")
        say(f"    나레이션: {s['tts_text']}")
        say(f"    프롬프트: {s['english_video_prompt'][:90]}...")
    if len(shots) > 3:
        say(f"\n  ... 외 {len(shots) - 3}개 컷")

    say("\n다음 단계: 각 prompt_XXX.txt 내용을 WanGP에 붙여넣어 영상을 만드세요.")
    say("(Phase 2에서 이 과정을 브라우저 UI로 더 쉽게 만들 예정이에요.)")


# ── argparse ──────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="app_cli.py",
        description="Local Video Factory — 대본을 컷 데이터와 프롬프트로 변환 (Phase 1)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="환경 점검 (Ollama/모델/폴더)")

    m = sub.add_parser("make", help="대본 → 컷 데이터 + 프롬프트 생성")
    m.add_argument("--title", required=True, help="프로젝트 제목")
    m.add_argument("--script", help="대본 텍스트 (직접 입력)")
    m.add_argument("--script-file", help="대본 파일 경로(.txt)")
    m.add_argument("--mode", default="emotional", choices=MODE_CHOICES,
                   help="입력 모드/스타일 (기본: emotional)")
    m.add_argument("--style", help="스타일 프리셋 직접 지정(선택, 기본은 mode와 동일)")
    m.add_argument("--duration", default="auto",
                   help="목표 길이(초) 또는 auto (기본: auto)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    try:
        cfg = config_loader.load_config()
    except config_loader.ConfigError as e:
        fail(str(e))
        return 1

    for w in cfg.get("warnings", []):
        say("[알림] " + w)

    if args.command == "check":
        return cmd_check(cfg)
    if args.command == "make":
        return cmd_make(cfg, args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
