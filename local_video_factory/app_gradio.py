#!/usr/bin/env python3
"""Local Video Factory — Phase 2 Gradio UI MVP

탭 1 "만들기": 대본 입력 → 분석 → 컷 생성
탭 2 "컷 보드": 컷 카드 확인 + 프롬프트 복사 + 전문가 모드(JSON)

초보자 중심. JSON/FPS/명령어 등은 기본 숨김(전문가 모드에서만 노출).
Phase 1 파이프라인(core/skills)을 그대로 재사용한다.

실행:  python app_gradio.py   →  브라우저에서 http://127.0.0.1:7860
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gradio as gr  # noqa: E402

from core import config_loader, llm_client, project_manager, prompt_library_manager  # noqa: E402
from skills import (  # noqa: E402
    script_parser_skill,
    shot_planner_skill,
    prompt_director_skill,
    supertonic_tts_skill,
    timeline_builder_skill,
    subtitle_sync_skill,
    ltx_prompt_enhancer_skill,
    prompt_quality_score,
    wangp_deepy_bridge_skill,
)
from tools import supertonic_engine, watcher, ffmpeg_tools, wangp_queue  # noqa: E402

# 사용자에게 보이는 라벨 → 내부 키
MODE_MAP = {
    "감성 쇼츠": "emotional",
    "제품 CF": "product_cf",
    "정보 전달 영상": "info",
    "모찌/동물 스토리": "mochi",
    "시니어 정보": "senior",
}
DURATION_MAP = {"자동": 0, "15초": 15, "30초": 30, "60초": 60}

# 사용자 친화적 목소리 이름 → Supertonic3 voice preset (문서 02)
VOICE_MAP = {
    "따뜻한 여성 목소리": "F1",
    "감성 내레이션": "F3",
    "밝은 안내 목소리": "F2",
    "차분한 남성 목소리": "M1",
    "시니어 정보 전달": "M2",
}

# 컷 상태값 → 사용자 문구
SHOT_STATUS_KO = {
    "planned": "장면 구성됨",
    "prompt_ready": "프롬프트 준비 완료",
    "video_ready": "영상 준비됨",
    "done": "완료",
}

INTRO = (
    "### 🎬 Local Video Factory\n"
    "대본을 넣으면, 로컬 AI가 장면을 나누고 영상 프롬프트·나레이션·자막까지 준비합니다."
)


def _progress_md(msg: str, frac: float) -> str:
    filled = int(round(frac * 20))
    bar = "█" * filled + "░" * (20 - filled)
    return f"**{msg}**\n\n`{bar}` {int(frac * 100)}%"


def _error_md(title: str, hint: str = "") -> str:
    out = f"### ⚠️ {title}"
    if hint:
        out += f"\n\n{hint}"
    return out


def run_environment_check() -> str:
    try:
        cfg = config_loader.load_config()
    except config_loader.ConfigError as e:
        return _error_md("설정을 읽지 못했어요", str(e))

    lines = ["### 🔍 환경 점검 결과", ""]
    server_ok, server_msg = llm_client.check_server(cfg)
    lines.append(("✅ " if server_ok else "❌ ") + server_msg)
    if server_ok:
        model_ok, model_msg, _ = llm_client.ensure_model(cfg)
        lines.append(("✅ " if model_ok else "❌ ") + model_msg.replace("\n", " "))
    root = os.path.abspath(cfg["project_root"])
    lines.append(f"📂 프로젝트 폴더: `{root}`")
    return "\n\n".join(lines)


def analyze(title, script, mode_label, dur_label, dur_custom):
    """대본 → 컷 → 프롬프트. 진행상황을 단계별로 yield 한다.

    outputs: (만들기_상태_md, shots_state, project_state)
    """
    # 입력 검증
    if not (script or "").strip():
        yield _error_md("대본이 비어 있어요", "왼쪽에 대본이나 아이디어를 입력해 주세요."), gr.skip(), gr.skip()
        return
    if not (title or "").strip():
        title = "제목 없는 영상"

    try:
        cfg = config_loader.load_config()
    except config_loader.ConfigError as e:
        yield _error_md("설정을 읽지 못했어요", str(e)), gr.skip(), gr.skip()
        return

    # Ollama 사전 점검 (쉬운 안내)
    server_ok, server_msg = llm_client.check_server(cfg)
    if not server_ok:
        yield _error_md(server_msg, "Ollama를 실행한 뒤 다시 시도해 주세요."), gr.skip(), gr.skip()
        return
    model_ok, model_msg, _ = llm_client.ensure_model(cfg)
    if not model_ok:
        yield _error_md("설정된 Qwen 모델을 찾지 못했어요", model_msg.replace("\n", "  ")), gr.skip(), gr.skip()
        return

    mode = MODE_MAP.get(mode_label, "emotional")
    if dur_label == "직접 입력":
        try:
            duration = max(0, int(dur_custom or 0))
        except (TypeError, ValueError):
            duration = 0
    else:
        duration = DURATION_MAP.get(dur_label, 0)

    # 프로젝트 생성
    pm = project_manager.create_project(
        cfg["project_root"], title,
        input_mode=mode, style_preset=mode,
        target_duration=duration, cfg=cfg,
    )
    pm.save_text("script_original.txt", script.strip())
    pm.save_text("idea.txt", script.strip())
    project = pm.load_json("project.json")

    try:
        yield _progress_md("대본을 분석하고 있어요...", 0.15), gr.skip(), gr.skip()
        pm.update_status("parsing_script")
        segments = script_parser_skill.parse_script(cfg, pm, project, script.strip())
        pm.update_status("script_parsed")

        yield _progress_md("장면을 6초 이하 컷으로 나누고 있어요...", 0.45), gr.skip(), gr.skip()
        pm.update_status("planning_shots")
        shots = shot_planner_skill.plan_shots(cfg, pm, project, segments)
        n = len(shots["shots"])
        pm.update_status("shots_ready", total_shots=n)

        yield _progress_md("영상 프롬프트를 만들고 있어요...", 0.75), gr.skip(), gr.skip()
        pm.update_status("generating_prompts", total_shots=n)
        prompt_director_skill.generate_prompts(cfg, pm, project, shots)
        pm.update_status("prompts_ready", total_shots=n)

    except llm_client.LLMError as e:
        pm.update_status("failed", last_error=e.message)
        hint = "같은 버튼을 한 번 더 눌러보세요. 대부분 해결돼요." if e.code == "bad_json" else ""
        yield _error_md(e.message, hint), gr.skip(), gr.skip()
        return
    except Exception as e:  # noqa: BLE001
        pm.update_status("failed", last_error=str(e))
        yield _error_md("예상치 못한 문제가 생겼어요", str(e)), gr.skip(), gr.skip()
        return

    shots_final = pm.load_json("shots.json")["shots"]
    done = _progress_md(f"완료! 컷 {len(shots_final)}개가 준비됐어요. 위의 '컷 보드' 탭에서 확인하세요.", 1.0)
    yield done, shots_final, pm.project_id


def check_tts_engine() -> str:
    try:
        cfg = config_loader.load_config()
    except config_loader.ConfigError as e:
        return _error_md("설정을 읽지 못했어요", str(e))
    st = supertonic_engine.probe(cfg)
    icon = "✅" if st["available"] else "❌"
    return f"{icon} {st['message']}"


def make_tts(project_id, voice_label):
    """현재 프로젝트의 컷별 나레이션을 만들고, 타임라인·자막까지 생성한다.

    outputs: (음성_상태_md, tts_state(list[shot]), 자막_textbox)
    """
    if not project_id:
        yield _error_md("아직 만든 영상이 없어요", "먼저 '만들기' 탭에서 컷을 만들어 주세요."), gr.skip(), gr.skip()
        return
    try:
        cfg = config_loader.load_config()
    except config_loader.ConfigError as e:
        yield _error_md("설정을 읽지 못했어요", str(e)), gr.skip(), gr.skip()
        return

    st = supertonic_engine.probe(cfg)
    if not st["available"]:
        yield (_error_md("나레이션 생성에 실패했어요", st["message"] +
                         "\n\n_또는 나레이션 없이 영상만 진행할 수도 있어요._"),
               gr.skip(), gr.skip())
        return

    pm = project_manager.ProjectManager(cfg["project_root"], project_id)
    project = pm.load_json("project.json")
    shots_data = pm.load_json("shots.json")
    voice = VOICE_MAP.get(voice_label, cfg.get("supertonic_default_voice", "F1"))
    total = len(shots_data["shots"])

    summary = None
    for ev in supertonic_tts_skill.synthesize_all(cfg, pm, project, shots_data, voice=voice):
        if ev[0] == "progress":
            _, i, tot, num = ev
            pm.update_status("generating_tts", current_shot=num, total_shots=tot)
            yield _progress_md(f"컷 {num:03d} 나레이션을 만들고 있어요... ({i}/{tot})",
                               (i - 1) / max(tot, 1)), gr.skip(), gr.skip()
        elif ev[0] == "done":
            summary = ev[1]

    # 타임라인 + 자막
    shots_data = pm.load_json("shots.json")
    timeline = timeline_builder_skill.build_timeline(cfg, pm, project, shots_data)
    srt = subtitle_sync_skill.build_srt(pm, shots_data, timeline)
    pm.update_status("tts_ready", total_shots=total)

    # 컷에 over_limit 정보 합쳐 렌더링용 state 구성
    over = {e["shot_number"]: e["over_limit"] for e in timeline["shots"]}
    shots_view = []
    for s in shots_data["shots"]:
        s = dict(s)
        s["_audio_path"] = pm.path(s.get("tts_file", "")) if s.get("tts_status") == "ready" else ""
        s["_over_limit"] = over.get(s["shot_number"], False)
        shots_view.append(s)

    # 결과 메시지
    lines = [f"### ✅ {summary['message']}"]
    if summary["failed_shots"]:
        lines.append(f"⚠️ 만들지 못한 컷: {summary['failed_shots']} (다시 시도하거나 문장을 확인해 주세요)")
    if timeline["warnings"]:
        lines.append("\n**나레이션이 영상보다 긴 컷이 있어요** (해결: 문장 짧게 / 말 속도 빠르게 / 영상 길이 늘리기):")
        for w in timeline["warnings"]:
            lines.append(f"- {w['message']}")
    lines.append("\n_컷별 미리듣기는 아래, 자막은 맨 아래에서 확인하세요._")

    yield "\n\n".join(lines), shots_view, gr.update(value=srt, visible=True)


# ── Phase 4: 영상 생성(WanGP) 탭 backend ──────────────────────
def _rec_settings_md(cfg) -> str:
    sec = round(cfg["default_frames_per_shot"] / cfg["default_fps"], 2)
    return (
        "**권장 WanGP 설정**\n\n"
        f"- 프레임 수: {cfg['default_frames_per_shot']}  ·  FPS: {cfg['default_fps']} (약 {sec}초)\n"
        f"- 해상도: {cfg['test_resolution']}  ·  최종 비율: {cfg['final_aspect_ratio']}\n"
        "- 한 번에 한 컷씩 생성 (배치 끄기), 720p·10초 이상 생성은 피하기"
    )


def _video_summary_md(pm, shots) -> str:
    total = len(shots["shots"])
    missing = watcher.shots_missing_video(pm, shots)
    ready = total - len(missing)
    md = f"**영상 {ready} / {total} 준비됨**"
    if missing:
        md += f"\n\n아직 영상이 없는 컷: {missing}"
    else:
        md += "\n\n🎉 모든 컷 영상이 준비됐어요! '최종 출력'(Phase 5)에서 합칠 수 있어요."
    return md


def _shot_fields(pm, shots, num):
    shot = next((s for s in shots["shots"] if s["shot_number"] == num), None)
    if not shot:
        return "", "", None
    vf = shot.get("video_file", "")
    vpath = pm.path(vf) if vf and os.path.isfile(pm.path(vf)) else None
    return shot.get("english_video_prompt", ""), shot.get("negative_prompt", ""), vpath


def _load_pm_shots(project_id):
    cfg = config_loader.load_config()
    pm = project_manager.ProjectManager(cfg["project_root"], project_id)
    shots = pm.load_json("shots.json")
    return cfg, pm, shots


def refresh_video(project_id):
    """영상 생성 탭 초기화: 컷 목록/현재 컷/프롬프트/미리보기/요약."""
    if not project_id:
        return (gr.update(choices=[], value=None), "", "", None,
                "_먼저 '만들기' 탭에서 컷을 만들어 주세요._")
    _cfg, pm, shots = _load_pm_shots(project_id)
    nums = [s["shot_number"] for s in shots["shots"]]
    cur = watcher.next_missing_shot(pm, shots) or (nums[0] if nums else None)
    p, n, v = _shot_fields(pm, shots, cur)
    return gr.update(choices=nums, value=cur), p, n, v, _video_summary_md(pm, shots)


def on_cur_shot_change(project_id, num):
    if not project_id or num is None:
        return "", "", None
    _cfg, pm, shots = _load_pm_shots(project_id)
    return _shot_fields(pm, shots, num)


def start_watch(project_id, folder):
    if not project_id:
        return [], gr.Timer(active=False), _error_md("먼저 컷을 만들어 주세요")
    if not folder or not os.path.isdir(folder):
        return [], gr.Timer(active=False), _error_md(
            "영상이 저장되는 폴더를 못 찾았어요", f"경로 확인: `{folder}`")
    known = watcher.snapshot(folder)
    return (known, gr.Timer(active=True),
            "👀 감시 중이에요. WanGP에 프롬프트를 붙여넣고 **Generate**를 누르세요. "
            "영상이 완성되면 자동으로 찾아올게요.")


def stop_watch():
    return gr.Timer(active=False), "감시를 멈췄어요."


def on_tick(project_id, folder, known, cur):
    """Timer 주기 호출: 새 영상 감지 → 현재/다음 컷에 자동 연결."""
    if not project_id or not folder or not os.path.isdir(folder):
        return known, gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip()
    _cfg, pm, shots = _load_pm_shots(project_id)
    fresh = watcher.find_new_stable(folder, known)
    if not fresh:
        return (known, "👀 감시 중... (새 영상 대기)",
                gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip())

    known = list(known) + fresh
    target = cur or watcher.next_missing_shot(pm, shots)
    assigned = []
    for f in fresh:
        if target is None:
            break
        watcher.assign_to_shot(pm, shots, target, f)
        assigned.append(target)
        target = watcher.next_missing_shot(pm, shots, after=target)

    if not assigned:
        return (known, "새 영상을 찾았지만 연결할 빈 컷이 없어요.",
                gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip())

    new_cur = target or assigned[-1]
    pm.update_status("shot_video_ready", total_shots=len(shots["shots"]))
    p, n, v = _shot_fields(pm, shots, new_cur)
    status = f"✅ 새 영상 {len(assigned)}개를 가져왔어요 (컷 {assigned} 연결)."
    return known, status, gr.update(value=new_cur), p, n, v, _video_summary_md(pm, shots)


def pick_file_assign(project_id, fileobj, cur):
    if not project_id:
        return gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip(), _error_md("먼저 컷을 만들어 주세요")
    if not fileobj:
        return gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip(), "영상 파일을 선택해 주세요."
    
    _cfg, pm, shots = _load_pm_shots(project_id)
    
    # file_count="multiple"인 경우 fileobj가 리스트로 제공됨
    files = fileobj if isinstance(fileobj, list) else [fileobj]
    assigned_shots = []
    
    target = cur or watcher.next_missing_shot(pm, shots)
    for f in files:
        if target is None:
            break
        path = f if isinstance(f, str) else getattr(f, "name", "")
        if not path:
            continue
        try:
            watcher.assign_to_shot(pm, shots, target, path)
            assigned_shots.append(target)
            target = watcher.next_missing_shot(pm, shots, after=target)
        except Exception as e:  # noqa: BLE001
            return gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip(), _error_md(f"컷 {target:03d}에 영상을 연결하지 못했어요", str(e))
            
    if not assigned_shots:
        return gr.skip(), gr.skip(), gr.skip(), gr.skip(), gr.skip(), "연결할 컷이 없거나 파일을 찾을 수 없습니다."
        
    pm.update_status("shot_video_ready", total_shots=len(shots["shots"]))
    new_cur = target or assigned_shots[-1]
    p, n, v = _shot_fields(pm, shots, new_cur)
    
    shot_str = ", ".join(f"{s:03d}" for s in assigned_shots)
    return (gr.update(value=new_cur), p, n, v, _video_summary_md(pm, shots),
            f"✅ 선택한 영상을 컷 {shot_str}에 연결했어요.")


def open_wangp_folder(folder):
    if watcher.open_folder(folder):
        return "📂 폴더를 열었어요."
    return _error_md("폴더를 열지 못했어요", f"경로 확인: `{folder}`")


def kill_ollama_process_ui():
    import subprocess
    p1 = subprocess.run(["taskkill", "/f", "/im", "ollama.exe"], capture_output=True, text=True)
    p2 = subprocess.run(["taskkill", "/f", "/im", "ollama_llama_server.exe"], capture_output=True, text=True)
    
    # 프로세스 종료 시그널 확인
    killed = "종료되었습니다" in p1.stdout or "종료되었습니다" in p2.stdout or "SUCCESS" in p1.stdout or "SUCCESS" in p2.stdout
    if killed:
        return "🛑 Ollama 및 백엔드 서버 프로세스를 강제 종료했습니다. (VRAM 해제 완료)"
    return "ℹ️ 종료할 Ollama 프로세스가 없거나 이미 종료된 상태입니다."


def launch_pinokio_ui():
    import subprocess
    import os
    import shutil
    
    paths = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "pinokio", "Pinokio.exe"),
        r"C:\Program Files\Pinokio\Pinokio.exe",
        r"C:\Program Files (x86)\Pinokio\Pinokio.exe"
    ]
    target = None
    for p in paths:
        if os.path.isfile(p):
            target = p
            break
            
    if target:
        subprocess.Popen([target])
        return f"🚀 Pinokio를 실행했습니다. ({os.path.basename(target)})"
        
    p_path = shutil.which("Pinokio.exe") or shutil.which("pinokio")
    if p_path:
        subprocess.Popen([p_path])
        return f"🚀 Pinokio를 실행했습니다. ({os.path.basename(p_path)})"
        
    return _error_md("Pinokio 실행 파일을 찾지 못했어요", "설치 경로(Local/Programs/pinokio)를 다시 한 번 확인해 주세요.")


QUEUE_SCOPE_MISSING = "아직 영상 없는 컷만"
QUEUE_SCOPE_ALL = "모든 컷"


def make_wangp_queue(project_id, scope):
    """전 컷 프롬프트로 WanGP Load Queue용 큐 파일을 만든다. outputs: (안내_md, 파일)."""
    if not project_id:
        return _error_md("먼저 '만들기' 탭에서 컷을 만들어 주세요"), None
    cfg, pm, shots = _load_pm_shots(project_id)
    project = pm.load_json("project.json")
    only = None
    if scope == QUEUE_SCOPE_MISSING:
        only = watcher.shots_missing_video(pm, shots)
        if not only:
            return "모든 컷에 이미 영상이 있어요. '모든 컷'을 선택하면 다시 만들 수 있어요.", None
    try:
        zip_path, n = wangp_queue.build_queue(cfg, pm, project, shots, only_shots=only)
    except wangp_queue.QueueTemplateError as e:
        return _error_md("큐 파일을 만들지 못했어요", str(e)), None
    except Exception as e:  # noqa: BLE001
        return _error_md("큐 파일을 만들지 못했어요", str(e)), None

    md = (
        f"### ✅ WanGP 큐 파일을 만들었어요 (컷 {n}개)\n\n"
        "**이렇게 쓰세요 (복붙 없이 한 번에 생성):**\n"
        "1. 아래 파일을 받아두고, WanGP 화면의 **Load Queue** 버튼으로 불러오세요.\n"
        "2. **Generate**를 누르면 전 컷이 차례로 생성돼요.\n"
        "3. 위에서 **영상 감시 시작**을 눌러두면 완성된 영상을 자동으로 가져옵니다."
    )
    return md, gr.update(value=zip_path, visible=True)


# ── Phase 5: 최종 출력 탭 backend ─────────────────────────────
FINAL_MODE_READY = "준비된 컷만 합치기"
FINAL_MODE_BLACK = "빈 컷은 검은 화면으로 채우기"


def final_status(project_id) -> str:
    if not project_id:
        return "_먼저 '만들기' 탭에서 컷을 만들어 주세요._"
    _cfg, pm, shots = _load_pm_shots(project_id)
    mc = ffmpeg_tools.missing_check(pm, shots)
    lines = [
        f"**총 {mc['total']}컷 중**",
        f"- 영상: {mc['videos_ready']} / {mc['total']} 준비됨",
        f"- 음성: {mc['audio_ready']} / {mc['total']} 준비됨",
        f"- 자막: {'준비됨' if mc['subtitles'] else '없음'}",
    ]
    if mc["missing_videos"]:
        lines.append(f"\n영상 없는 컷: {mc['missing_videos']} → '영상 생성' 탭에서 만들어 주세요.")
    if not mc["missing_videos"]:
        lines.append("\n🎉 모든 컷 영상이 준비됐어요. 최종 영상을 만들 수 있어요!")
    return "\n".join(lines)


def make_final(project_id, with_subtitles, with_audio, mode):
    """final.mp4 생성. outputs: (상태_md, 결과영상)."""
    if not project_id:
        yield _error_md("아직 만든 영상이 없어요", "먼저 '만들기' 탭에서 컷을 만들어 주세요."), gr.skip()
        return
    cfg, pm, shots = _load_pm_shots(project_id)
    ok, ff_msg = ffmpeg_tools.check_ffmpeg(cfg)
    if not ok:
        yield _error_md("최종 영상 합치기에 실패했어요", ff_msg), gr.skip()
        return

    project = pm.load_json("project.json")
    timeline = pm.load_json("timeline.json") if pm.exists("timeline.json") else {}
    include = "all" if mode == FINAL_MODE_BLACK else "ready"
    black = mode == FINAL_MODE_BLACK

    pm.update_status("merging_video_audio", total_shots=len(shots["shots"]))
    result = None
    for ev in ffmpeg_tools.build_final(
        cfg, pm, project, shots, timeline,
        include=include, with_audio=with_audio,
        with_subtitles=with_subtitles, black_for_missing=black,
    ):
        if ev[0] == "progress":
            _, i, tot, msg = ev
            yield _progress_md(msg, i / max(tot, 1)), gr.skip()
        elif ev[0] == "done":
            result = ev[1]

    if not result or not result.get("ok"):
        pm.update_status("failed", last_error=(result or {}).get("message", ""))
        hint = (result or {}).get("hint", "")
        yield _error_md((result or {}).get("message", "최종 영상 합치기에 실패했어요"), hint), gr.skip()
        return

    pm.update_status("final_ready", total_shots=len(shots["shots"]))
    yield f"### ✅ {result['message']}\n\n_아래에서 미리보고, 결과 폴더를 열 수 있어요._", result["path"]


def open_result(project_id) -> str:
    if not project_id:
        return "_먼저 영상을 만들어 주세요._"
    _cfg, pm, _shots = _load_pm_shots(project_id)
    if ffmpeg_tools.open_result_folder(pm):
        return "📂 결과 폴더를 열었어요."
    return _error_md("폴더를 열지 못했어요")


# ── Phase 6: 저장/이어하기 backend ────────────────────────────
def _progress_pct(p) -> int:
    try:
        return int(round(float(p) * 100))
    except (TypeError, ValueError):
        return 0


def list_project_choices():
    """이전 프로젝트 드롭다운 choices: [(label, project_id), ...] (최신순)."""
    try:
        cfg = config_loader.load_config()
        cards = project_manager.list_projects(cfg["project_root"])
    except Exception:  # noqa: BLE001
        cards = []
    choices = []
    for c in cards:
        date = (c.get("created_at", "") or "")[:10]
        final = " · ✅완성" if c.get("has_final") else ""
        # 라벨 중복으로 인한 Gradio 컴포넌트의 중복 필터링을 방지하기 위해 고유 ID를 추가
        label = (f"{c['title']} ({c['project_id']})  ·  {_progress_pct(c['progress'])}%  ·  "
                 f"{c['status_message']}  ·  {date}{final}")
        choices.append((label, c["project_id"]))
    return choices


def refresh_projects():
    return gr.update(choices=list_project_choices())


def delete_project_ui(project_id, current_project_id):
    if not project_id:
        return current_project_id, gr.skip(), "삭제할 프로젝트를 먼저 선택해 주세요."
    try:
        cfg = config_loader.load_config()
        ok = project_manager.delete_project(cfg["project_root"], project_id)
    except Exception as e:  # noqa: BLE001
        return current_project_id, gr.skip(), f"❌ 에러가 발생했습니다: {e}"
        
    if not ok:
        return current_project_id, gr.skip(), f"❌ '{project_id}' 프로젝트를 삭제하지 못했습니다."
    
    # 만약 현재 열린 프로젝트를 지웠다면 상태 해제
    next_proj = None if project_id == current_project_id else current_project_id
    choices = list_project_choices()
    dropdown_update = gr.update(choices=choices, value=None)
    
    return next_proj, dropdown_update, f"🗑️ '{project_id}' 프로젝트를 삭제했습니다."


def enhance_single_prompt_ui(project_id, shot_number, char_lock=""):
    if not project_id or shot_number is None:
        return gr.skip(), gr.skip(), "프로젝트를 먼저 로드해 주세요."
    cfg, pm, shots_data = _load_pm_shots(project_id)
    project = pm.load_json("project.json")
    
    shot = next((s for s in shots_data["shots"] if s["shot_number"] == shot_number), None)
    if not shot:
        return gr.skip(), gr.skip(), f"컷 {shot_number}을 찾을 수 없습니다."
        
    # LTX-2 프롬프트 강화
    enhanced = ltx_prompt_enhancer_skill.enhance_prompt(
        cfg, pm, shot.get("korean_description", ""),
        shot.get("keywords", []), shot.get("emotion", "neutral"),
        project.get("style_preset", ""), character_lock_prompt=char_lock,
        duration=shot.get("duration", 5.875)
    )
    shot["ltx_prompt"] = enhanced["ltx_prompt"]
    shot["ltx_negative_prompt"] = enhanced["ltx_negative_prompt"]
    
    # 채점 및 수동 개선 반영
    score = prompt_quality_score.evaluate_prompt(enhanced["ltx_prompt"])
    shot["prompt_quality_score"] = score
    
    # Deepy 팩 갱신
    shot["deepy_prompt_pack"] = wangp_deepy_bridge_skill.build_deepy_pack(shot, char_lock)
    
    # 개별 파일 저장
    pm.save_json("shots.json", shots_data)
    wangp_deepy_bridge_skill.export_wangp_files(pm, shots_data, char_lock)
    
    # 갱신된 shots 리스트 반환
    return shots_data["shots"], shots_data["shots"], f"✨ 컷 {shot_number:03d}의 프롬프트를 LTX-2 규격으로 강화하고 품질 채점({score['overall']}점)을 마쳤습니다!"


def save_to_library_ui(project_id, shot_number, category, name):
    if not project_id or shot_number is None:
        return "프로젝트 또는 컷을 지정해 주세요."
    cfg, pm, shots_data = _load_pm_shots(project_id)
    shot = next((s for s in shots_data["shots"] if s["shot_number"] == shot_number), None)
    if not shot:
        return "지정한 컷 데이터를 찾을 수 없습니다."
        
    pos = shot.get("ltx_prompt", shot.get("english_video_prompt", ""))
    neg = shot.get("ltx_negative_prompt", shot.get("negative_prompt", ""))
    
    if category == "캐릭터 락":
        path = prompt_library_manager.save_character_prompt(name, pos)
    elif category == "스타일 프리셋":
        path = prompt_library_manager.save_style_prompt(name, pos, neg)
    else:
        path = prompt_library_manager.save_success_case(project_id, shot_number, shot)
        
    return f"💾 성공 프롬프트를 [{category}]로 '{name}' 이름으로 저장했습니다.\n경로: {os.path.basename(path)}"


def refresh_lab_ui(project_id):
    if not project_id:
        return gr.update(choices=[], value=None)
    cfg, pm, shots_data = _load_pm_shots(project_id)
    nums = [s["shot_number"] for s in shots_data["shots"]]
    if not nums:
        return gr.update(choices=[], value=None)
    return gr.update(choices=nums, value=nums[0])


def on_lab_shot_change(project_id, num):
    if not project_id or num is None:
        return "", "", "", "#### 📊 품질 점수: -", "", "", ""
    cfg, pm, shots_data = _load_pm_shots(project_id)
    shot = next((s for s in shots_data["shots"] if s["shot_number"] == num), None)
    if not shot:
        return "", "", "", "#### 📊 품질 점수: -", "", "", ""
    
    base = shot.get("base_prompt", shot.get("english_video_prompt", ""))
    ltx = shot.get("ltx_prompt", base)
    neg = shot.get("ltx_negative_prompt", shot.get("negative_prompt", ""))
    
    # 채점
    score = shot.get("prompt_quality_score", {})
    if not score or score.get("overall", 0) == 0:
        score = prompt_quality_score.evaluate_prompt(ltx)
        
    score_md = f"#### 📊 품질 점수: **{score.get('overall', 0)}점**"
    feedback = []
    if score.get("issues"):
        feedback.append("■ 발견된 이슈:")
        for iss in score["issues"]:
            feedback.append(f"- {iss}")
    if score.get("suggestions"):
        feedback.append("\n■ 개선 제안:")
        for sug in score["suggestions"]:
            feedback.append(f"- {sug}")
    feedback_str = "\n".join(feedback) if feedback else "최고 등급의 프롬프트입니다!"
    
    pack = shot.get("deepy_prompt_pack", {})
    if not pack or not pack.get("positive_prompt"):
        pack = wangp_deepy_bridge_skill.build_deepy_pack(shot)
        
    copy_ready = pack.get("copy_ready_prompt", "")
    pack_str = json.dumps(pack, ensure_ascii=False, indent=2)
    
    return base, ltx, neg, score_md, feedback_str, copy_ready, pack_str


def save_lab_prompt_ui(project_id, num, ltx_prompt, neg_prompt, char_lock):
    if not project_id or num is None:
        return gr.skip(), "프로젝트를 먼저 선택해 주세요."
    cfg, pm, shots_data = _load_pm_shots(project_id)
    shot = next((s for s in shots_data["shots"] if s["shot_number"] == num), None)
    if not shot:
        return gr.skip(), "컷을 찾을 수 없습니다."
        
    shot["ltx_prompt"] = ltx_prompt
    shot["ltx_negative_prompt"] = neg_prompt
    
    # 다시 채점
    score = prompt_quality_score.evaluate_prompt(ltx_prompt)
    shot["prompt_quality_score"] = score
    
    # Deepy 팩 갱신
    shot["deepy_prompt_pack"] = wangp_deepy_bridge_skill.build_deepy_pack(shot, char_lock)
    
    pm.save_json("shots.json", shots_data)
    wangp_deepy_bridge_skill.export_wangp_files(pm, shots_data, char_lock)
    
    return shots_data["shots"], f"💾 컷 {num:03d}의 수동 변경 사항 및 Deepy 팩을 성공적으로 저장하고 품질 채점({score['overall']}점)을 갱신했습니다."


def _tts_view_from(pm, shots_data, timeline):
    """이어하기 시 음성 탭 미리듣기용 state 재구성."""
    over = {e["shot_number"]: e["over_limit"] for e in (timeline or {}).get("shots", [])}
    view = []
    for s in shots_data["shots"]:
        s2 = dict(s)
        ready = s.get("tts_status") == "ready" and s.get("tts_file")
        s2["_audio_path"] = pm.path(s["tts_file"]) if ready and os.path.isfile(pm.path(s["tts_file"])) else ""
        s2["_over_limit"] = over.get(s["shot_number"], False)
        view.append(s2)
    return view


def resume_project(project_id):
    """선택한 프로젝트를 불러와 상태를 채우고 '컷 보드' 탭으로 이동.

    outputs: (project_state, shots_state, tts_state, 안내_md, main_tabs)
    """
    if not project_id:
        return (gr.skip(), gr.skip(), gr.skip(),
                "이어서 작업할 프로젝트를 먼저 선택해 주세요.", gr.skip())
    cfg = config_loader.load_config()
    pm = project_manager.ProjectManager(cfg["project_root"], project_id)
    if not pm.exists("project.json"):
        return gr.skip(), gr.skip(), gr.skip(), _error_md("프로젝트를 찾지 못했어요"), gr.skip()

    project = pm.load_json("project.json")
    shots_data = pm.load_json("shots.json") if pm.exists("shots.json") else {"shots": []}
    timeline = pm.load_json("timeline.json") if pm.exists("timeline.json") else {}
    status = pm.load_json("status.json") if pm.exists("status.json") else {}
    shots = shots_data.get("shots", [])
    tts_view = _tts_view_from(pm, shots_data, timeline) if shots else []

    # 누락 현황
    missing_v = [s["shot_number"] for s in shots
                 if not s.get("video_file") or not os.path.isfile(pm.path(s.get("video_file", "")))]
    md = [
        f"### ▶️ '{project.get('project_title', project_id)}' 이어서 작업",
        f"- 진행 상태: {status.get('user_status_message', '준비 중')} ({_progress_pct(status.get('progress'))}%)",
        f"- 컷 수: {len(shots)}개",
    ]
    if missing_v:
        md.append(f"- 아직 영상 없는 컷: {missing_v}")
    md.append("\n_'컷 보드' 탭으로 이동했어요. 음성/영상/최종 출력 탭도 이어서 쓸 수 있어요._")

    return project_id, shots, tts_view, "\n".join(md), gr.Tabs(selected="board")


def start_new():
    """새 영상 만들기: 상태 초기화 후 '만들기' 탭으로 이동."""
    return None, [], [], "새 영상을 시작해요. '만들기' 탭에서 대본을 넣어주세요.", gr.Tabs(selected="make")


# ── Phase 7+8: 진단/설정 backend ──────────────────────────────
def run_full_diagnostics() -> str:
    try:
        cfg = config_loader.load_config()
    except config_loader.ConfigError as e:
        return _error_md("설정을 읽지 못했어요", str(e))

    lines = ["### 🔍 전체 진단", ""]

    ok, msg = llm_client.check_server(cfg)
    lines.append(("✅ " if ok else "❌ ") + msg)
    if ok:
        mok, mmsg, _ = llm_client.ensure_model(cfg)
        lines.append(("✅ " if mok else "⚠️ ") + mmsg.replace("\n", "  "))

    st = supertonic_engine.probe(cfg)
    lines.append(("✅ " if st["available"] else "⚠️ ") + st["message"].replace("\n", "  "))

    wan = cfg.get("wan_gp_output_path", "")
    if wan and os.path.isdir(wan):
        lines.append(f"✅ WanGP output 폴더 확인: `{wan}`")
    else:
        lines.append(f"⚠️ WanGP output 폴더를 못 찾았어요: `{wan}` (아래에서 다시 지정)")

    fok, fmsg = ffmpeg_tools.check_ffmpeg(cfg)
    lines.append(("✅ " if fok else "❌ ") + fmsg)
    import shutil as _sh
    lines.append(("✅ ffprobe 준비됨" if _sh.which(cfg.get("ffprobe_path", "ffprobe"))
                  else "⚠️ ffprobe를 못 찾았어요 (최종 합성에 필요)"))

    return "\n\n".join(lines)


def get_installed_models():
    """설치된 모델 중 사용 가능한 것만 (문서 규칙상 gemma/lmstudio 계열 제외)."""
    try:
        cfg = config_loader.load_config()
        models = llm_client.list_models(cfg)
    except Exception:  # noqa: BLE001
        return []
    forbidden = ("gemma", "lmstudio")
    return [m for m in models if not any(f in m.lower() for f in forbidden)]


def save_model(model) -> str:
    if not model:
        return "사용할 모델을 선택해 주세요."
    try:
        config_loader.update_config_values({"ollama_model": model})
        return f"✅ 기본 모델을 '{model}'(으)로 저장했어요."
    except Exception as e:  # noqa: BLE001
        return _error_md("모델 저장에 실패했어요", str(e))


def save_paths(wan_out, supertonic_home, ffmpeg_path) -> str:
    updates = {}
    if wan_out:
        updates["wan_gp_output_path"] = wan_out.strip()
    if supertonic_home:
        updates["supertonic_home"] = supertonic_home.strip()
    if ffmpeg_path:
        updates["ffmpeg_path"] = ffmpeg_path.strip()
    if not updates:
        return "저장할 경로가 없어요."
    try:
        config_loader.update_config_values(updates)
        return "✅ 경로를 저장했어요. (일부 화면은 앱을 다시 켜면 반영돼요.)"
    except Exception as e:  # noqa: BLE001
        return _error_md("경로 저장에 실패했어요", str(e))


def save_video_settings(fps, frames, resolution) -> str:
    try:
        updates = {
            "default_fps": int(fps),
            "default_frames_per_shot": int(frames),
            "test_resolution": str(resolution).strip(),
        }
        config_loader.update_config_values(updates)
        sec = round(int(frames) / max(int(fps), 1), 2)
        return f"✅ 영상 설정을 저장했어요. (컷당 약 {sec}초)"
    except (TypeError, ValueError):
        return "FPS와 프레임 수는 숫자로 입력해 주세요."
    except Exception as e:  # noqa: BLE001
        return _error_md("영상 설정 저장에 실패했어요", str(e))


# ── 전문가 모드: 파일/로그 뷰어 ───────────────────────────────
_EXPERT_FILES = ["shots.json", "script_segments.json", "timeline.json",
                 "status.json", "project.json", "captions.srt", "negative_prompt.txt"]


def list_project_files(project_id):
    if not project_id:
        return gr.update(choices=[], value=None)
    cfg = config_loader.load_config()
    pm = project_manager.ProjectManager(cfg["project_root"], project_id)
    names = [f for f in _EXPERT_FILES if pm.exists(f)]
    import glob as _g
    names += [os.path.basename(p) for p in sorted(_g.glob(pm.path("prompt_*.txt")))]
    return gr.update(choices=names, value=(names[0] if names else None))


def view_file(project_id, name):
    if not project_id or not name:
        return ""
    cfg = config_loader.load_config()
    pm = project_manager.ProjectManager(cfg["project_root"], project_id)
    try:
        with open(pm.path(name), "r", encoding="utf-8-sig") as f:
            return f.read()
    except Exception as e:  # noqa: BLE001
        return f"(열지 못했어요: {e})"


def list_log_files(project_id):
    if not project_id:
        return gr.update(choices=[], value=None)
    cfg = config_loader.load_config()
    pm = project_manager.ProjectManager(cfg["project_root"], project_id)
    import glob as _g
    names = [os.path.basename(p) for p in sorted(_g.glob(pm.path("logs", "*.log")))]
    return gr.update(choices=names, value=(names[0] if names else None))


def view_log(project_id, name):
    if not project_id or not name:
        return ""
    cfg = config_loader.load_config()
    pm = project_manager.ProjectManager(cfg["project_root"], project_id)
    try:
        with open(pm.path("logs", name), "r", encoding="utf-8") as f:
            data = f.read()
        return data[-8000:]  # 끝부분만
    except Exception as e:  # noqa: BLE001
        return f"(열지 못했어요: {e})"


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Local Video Factory") as demo:
        shots_state = gr.State([])
        project_state = gr.State(None)
        tts_state = gr.State([])

        gr.Markdown(INTRO)

        with gr.Accordion("🔍 환경 점검 (Ollama가 켜져 있나요?)", open=False):
            check_btn = gr.Button("환경 점검하기")
            check_out = gr.Markdown()
            check_btn.click(run_environment_check, outputs=check_out)

        with gr.Tabs() as main_tabs:
            # ── 탭 0: 시작 / 이어하기 ─────────────────────
            with gr.Tab("🏠 시작", id="start"):
                gr.Markdown("이전 작업을 이어서 하거나, 새 영상을 만들 수 있어요.")
                with gr.Row():
                    project_dd = gr.Dropdown(label="이전 작업 (최근 프로젝트)",
                                             choices=list_project_choices(), scale=3)
                    refresh_proj_btn = gr.Button("🔄 목록 새로고침", scale=1)
                with gr.Row():
                    resume_btn = gr.Button("▶️ 이전 작업 이어하기", variant="primary")
                    new_btn = gr.Button("✨ 새 영상 만들기")
                    delete_btn = gr.Button("🗑️ 프로젝트 삭제", variant="stop")
                start_status = gr.Markdown()

            # ── 탭 1: 만들기 ──────────────────────────────
            with gr.Tab("✏️ 만들기", id="make"):
                with gr.Row():
                    with gr.Column(scale=3):
                        title_in = gr.Textbox(label="프로젝트 제목", placeholder="예: 비 오는 날 모찌")
                        script_in = gr.Textbox(
                            label="대본 / 아이디어",
                            placeholder="대본을 붙여넣거나 한 줄 아이디어를 적어주세요.",
                            lines=10,
                        )
                    with gr.Column(scale=2):
                        mode_in = gr.Radio(
                            list(MODE_MAP.keys()), value="감성 쇼츠", label="입력 모드 / 스타일",
                        )
                        dur_in = gr.Radio(
                            ["자동", "15초", "30초", "60초", "직접 입력"],
                            value="자동", label="목표 길이",
                        )
                        dur_custom = gr.Number(
                            label="직접 입력(초)", value=15, visible=False, minimum=4,
                        )

                        def _toggle_custom(d):
                            return gr.update(visible=(d == "직접 입력"))

                        dur_in.change(_toggle_custom, dur_in, dur_custom)

                        with gr.Accordion("고급 설정 (전문가용)", open=False):
                            gr.Markdown(
                                "현재 기본값 (config.yaml에서 변경):\n"
                                "- 컷당 최대 길이: 6초\n"
                                "- 프레임 수: 141 · FPS: 24 (≈ 5.875초/컷)\n"
                                "- 해상도: 512x320 · 최종 비율: 9:16\n\n"
                                "_세밀 조정은 Phase 8 전문가 모드에서 제공될 예정이에요._"
                            )

                make_btn = gr.Button("🎬 분석하고 컷 만들기", variant="primary", size="lg")
                make_status = gr.Markdown()

            # ── 탭 2: 컷 보드 ─────────────────────────────
            with gr.Tab("🎞️ 컷 보드", id="board"):
                with gr.Row():
                    gr.Markdown("생성된 컷을 카드로 확인하고, 프롬프트를 복사해 WanGP에 붙여넣으세요.")
                    expert_toggle = gr.Checkbox(label="전문가 모드 (JSON 보기)", value=False)

                @gr.render(inputs=[shots_state, expert_toggle])
                def render_board(shots, expert):
                    if not shots:
                        gr.Markdown(
                            "_아직 컷이 없어요. '만들기' 탭에서 대본을 넣고 "
                            "**분석하고 컷 만들기**를 눌러주세요._"
                        )
                        return

                    total_sec = round(sum(s.get("duration", 0) for s in shots), 1)
                    gr.Markdown(f"**총 {len(shots)}개 컷 · 예상 길이 약 {total_sec}초**")

                    for s in shots:
                        with gr.Group():
                            status_ko = SHOT_STATUS_KO.get(s.get("status", ""), s.get("status", ""))
                            gr.Markdown(
                                f"#### 컷 {s['shot_number']:03d}  ·  약 {s.get('duration', 0)}초  "
                                f"·  {status_ko}"
                            )
                            gr.Markdown(
                                f"**장면:** {s.get('korean_description', '')}\n\n"
                                f"**나레이션:** {s.get('tts_text', '')}"
                            )
                            gr.Textbox(
                                value=s.get("english_video_prompt", ""),
                                label="영상 프롬프트 (오른쪽 복사 아이콘 클릭)",
                                lines=3, interactive=False, buttons=["copy"],
                            )
                            if expert:
                                gr.Textbox(
                                    value=s.get("negative_prompt", ""),
                                    label="negative prompt",
                                    lines=2, interactive=False, buttons=["copy"],
                                )
                            
                            # 컷 카드 액션 버튼 추가
                            with gr.Row():
                                enhance_card_btn = gr.Button("✨ LTX2 프롬프트 개선", variant="secondary")
                                copy_ready_btn = gr.Button("📋 WanGP용 복사", variant="secondary")
                                show_pack_btn = gr.Button("📦 Deepy Pack 보기", variant="secondary")
                                score_card_btn = gr.Button("📊 품질 점수", variant="secondary")
                                save_lib_card_btn = gr.Button("💾 성공 프롬프트 저장", variant="secondary")
                            
                            card_status = gr.Markdown()
                            
                            # 카드 내 버튼 이벤트 바인딩
                            def _enhance_card_fn(proj_id, shot_num=s["shot_number"]):
                                _, new_shots, msg = enhance_single_prompt_ui(proj_id, shot_num)
                                return new_shots, msg
                            
                            enhance_card_btn.click(
                                _enhance_card_fn,
                                inputs=[project_state],
                                outputs=[shots_state, card_status]
                            )
                            
                            def _copy_ready_fn(proj_id, shot_num=s["shot_number"]):
                                if not proj_id:
                                    return "프로젝트를 먼저 로드해 주세요."
                                _, _, _, _, _, copy_ready, _ = on_lab_shot_change(proj_id, shot_num)
                                return f"📋 복사할 텍스트:\n\n{copy_ready}"
                            copy_ready_btn.click(_copy_ready_fn, inputs=[project_state], outputs=[card_status])
                            
                            def _show_pack_fn(proj_id, shot_num=s["shot_number"]):
                                if not proj_id:
                                    return "프로젝트를 먼저 로드해 주세요."
                                _, _, _, _, _, _, pack_str = on_lab_shot_change(proj_id, shot_num)
                                return f"📦 Deepy Pack JSON:\n```json\n{pack_str}\n```"
                            show_pack_btn.click(_show_fn := _show_pack_fn, inputs=[project_state], outputs=[card_status])
                            
                            def _score_card_fn(proj_id, shot_num=s["shot_number"]):
                                if not proj_id:
                                    return "프로젝트를 먼저 로드해 주세요."
                                _, _, _, score_md, feedback, _, _ = on_lab_shot_change(proj_id, shot_num)
                                return f"{score_md}\n\n{feedback}"
                            score_card_btn.click(_score_card_fn, inputs=[project_state], outputs=[card_status])
                            
                            def _save_lib_card_fn(proj_id, shot_num=s["shot_number"]):
                                if not proj_id:
                                    return "프로젝트를 먼저 로드해 주세요."
                                return save_to_library_ui(proj_id, shot_num, "성공 케이스", f"shot_{shot_num:03d}")
                            save_lib_card_btn.click(_save_lib_card_fn, inputs=[project_state], outputs=[card_status])

                    if expert:
                        gr.Markdown("---\n#### 🛠️ shots.json (전문가)")
                        gr.Code(
                            value=json.dumps(shots, ensure_ascii=False, indent=2),
                            language="json",
                        )

            # ── 탭 3: 🧪 프롬프트 연구소 ───────────────────
            with gr.Tab("🧪 프롬프트 연구소", id="prompt_lab"):
                gr.Markdown("비디오 생성 프롬프트를 LTX-2 / WanGP 규격에 맞춰 미세 조정하고 검사하는 전용 공간입니다.")
                with gr.Row():
                    lab_shot_dd = gr.Dropdown(label="선택된 컷", choices=[], scale=2)
                    lab_refresh_btn = gr.Button("🔄 컷 목록 새로고침", scale=1)
                
                with gr.Row():
                    with gr.Column(scale=3):
                        lab_char_lock = gr.Textbox(
                            label="캐릭터 락 프롬프트 (예: Mochi, red hoodie, white dog)",
                            placeholder="이 컷이나 프로젝트 전체에 고정할 캐릭터 특성을 적으세요.",
                            lines=1
                        )
                        lab_base = gr.Textbox(label="기본 대본 프롬프트 (Base)", lines=3, interactive=False)
                        lab_ltx = gr.Textbox(label="LTX-2 강화 프롬프트 (Positive)", lines=4, interactive=True)
                        lab_neg = gr.Textbox(label="LTX-2 부정 프롬프트 (Negative)", lines=2, interactive=True)
                        
                        with gr.Row():
                            lab_enhance_btn = gr.Button("🪄 LTX-2 규격 자동 강화", variant="primary")
                            lab_save_btn = gr.Button("💾 변경사항 및 Deepy 팩 저장", variant="secondary")
                            
                    with gr.Column(scale=2):
                        lab_score_md = gr.Markdown("#### 📊 품질 점수: -")
                        lab_feedback = gr.Textbox(label="피드백 및 개선 제안", lines=6, interactive=False)
                        lab_copy_ready = gr.Textbox(label="WanGP 바로 복사용 텍스트", lines=4, interactive=False, buttons=["copy"])
                
                with gr.Row():
                    with gr.Accordion("📦 Deepy JSON 패키지 뷰어", open=False):
                        lab_pack_json = gr.Code(label="wangp_deepy_pack_NNN.json", language="json")
                
                with gr.Row():
                    with gr.Accordion("💾 성공 프롬프트 라이브러리에 백업", open=False):
                        with gr.Row():
                            lib_category = gr.Radio(["캐릭터 락", "스타일 프리셋", "성공 케이스"], value="성공 케이스", label="라이브러리 분류")
                            lib_name = gr.Textbox(label="보관 명칭", placeholder="예: mochi_smile_natural")
                            lib_save_btn = gr.Button("📁 라이브러리 저장", variant="primary")
                        lib_status = gr.Markdown()
                        
                        lib_save_btn.click(
                            save_to_library_ui,
                            inputs=[project_state, lab_shot_dd, lib_category, lib_name],
                            outputs=[lib_status]
                        )

                # 이벤트 바인딩
                lab_refresh_btn.click(refresh_lab_ui, inputs=[project_state], outputs=[lab_shot_dd])
                lab_shot_dd.change(
                    on_lab_shot_change,
                    inputs=[project_state, lab_shot_dd],
                    outputs=[lab_base, lab_ltx, lab_neg, lab_score_md, lab_feedback, lab_copy_ready, lab_pack_json]
                )
                lab_enhance_btn.click(
                    enhance_single_prompt_ui,
                    inputs=[project_state, lab_shot_dd, lab_char_lock],
                    outputs=[shots_state, shots_state, lib_status]
                ).then(
                    on_lab_shot_change,
                    inputs=[project_state, lab_shot_dd],
                    outputs=[lab_base, lab_ltx, lab_neg, lab_score_md, lab_feedback, lab_copy_ready, lab_pack_json]
                )
                lab_save_btn.click(
                    save_lab_prompt_ui,
                    inputs=[project_state, lab_shot_dd, lab_ltx, lab_neg, lab_char_lock],
                    outputs=[shots_state, lib_status]
                ).then(
                    on_lab_shot_change,
                    inputs=[project_state, lab_shot_dd],
                    outputs=[lab_base, lab_ltx, lab_neg, lab_score_md, lab_feedback, lab_copy_ready, lab_pack_json]
                )

            # ── 탭 4: 음성/자막 ───────────────────────────
            with gr.Tab("🔊 음성/자막", id="audio"):
                gr.Markdown("컷별 나레이션(Supertonic3)과 자막을 만들고 미리 들어보세요.")
                tts_engine_md = gr.Markdown()
                with gr.Row():
                    voice_in = gr.Dropdown(
                        list(VOICE_MAP.keys()), value="따뜻한 여성 목소리",
                        label="목소리", scale=3,
                    )
                    recheck_btn = gr.Button("🔍 음성 엔진 점검", scale=1)
                tts_btn = gr.Button("🎙️ 나레이션 만들기", variant="primary", size="lg")
                tts_status = gr.Markdown()

                recheck_btn.click(check_tts_engine, outputs=tts_engine_md)
                # 탭이 열릴 때 엔진 상태를 자동 표시
                demo.load(check_tts_engine, outputs=tts_engine_md)

                @gr.render(inputs=[tts_state])
                def render_audio(shots):
                    if not shots:
                        gr.Markdown("_'나레이션 만들기'를 누르면 컷별 음성이 여기에 나타나요._")
                        return
                    for s in shots:
                        with gr.Group():
                            num = s["shot_number"]
                            dur = s.get("tts_duration", 0)
                            warn = "  ⚠️ 영상보다 긺" if s.get("_over_limit") else ""
                            gr.Markdown(f"**컷 {num:03d}** · {dur}초{warn}\n\n_{s.get('tts_text', '')}_")
                            if s.get("_audio_path"):
                                gr.Audio(value=s["_audio_path"], label="나레이션 미리듣기",
                                         interactive=False)
                            else:
                                gr.Markdown("_이 컷은 나레이션을 만들지 못했어요._")

                gr.Markdown("---\n#### 📝 자막 (captions.srt)")
                srt_box = gr.Textbox(label="자막 미리보기", lines=10, visible=False,
                                     buttons=["copy"], interactive=False)

                tts_btn.click(
                    make_tts,
                    inputs=[project_state, voice_in],
                    outputs=[tts_status, tts_state, srt_box],
                )

            # ── 탭 5: 영상 생성 (WanGP 도우미) ─────────────
            with gr.Tab("🎬 영상 생성", id="video"):
                try:
                    _cfg0 = config_loader.load_config()
                    _out0 = _cfg0.get("wan_gp_output_path", "")
                    _rec0 = _rec_settings_md(_cfg0)
                except Exception:  # noqa: BLE001
                    _out0, _rec0 = "", ""

                gr.Markdown(
                    "아래 프롬프트를 WanGP에 붙여넣고 **Generate**를 누르세요. "
                    "영상이 완성되면 제가 자동으로 찾아올게요."
                )
                watch_known = gr.State([])

                with gr.Row():
                    cur_shot_dd = gr.Dropdown(label="현재 작업할 컷", choices=[], scale=2)
                    refresh_vid_btn = gr.Button("🔄 컷 불러오기/새로고침", scale=1)

                cur_prompt = gr.Textbox(label="복사할 프롬프트", lines=4,
                                        interactive=False, buttons=["copy"])
                cur_negative = gr.Textbox(label="Negative Prompt", lines=2,
                                          interactive=False, buttons=["copy"])
                gr.Markdown(_rec0)

                with gr.Accordion("⚡ 한 번에 만들기 (WanGP 큐 파일) — 복붙 없이", open=False):
                    gr.Markdown(
                        "컷 프롬프트 전체를 담은 큐 파일을 만들어요. "
                        "WanGP의 **Load Queue**로 불러와 **Generate**만 누르면 전 컷이 생성됩니다."
                    )
                    with gr.Row():
                        queue_scope = gr.Radio([QUEUE_SCOPE_MISSING, QUEUE_SCOPE_ALL],
                                               value=QUEUE_SCOPE_MISSING, label="대상", scale=2)
                        queue_btn = gr.Button("📦 큐 파일 만들기", variant="primary", scale=1)
                    queue_status = gr.Markdown()
                    queue_file = gr.File(label="WanGP 큐 파일 (Load Queue로 불러오기)", visible=False)
                    queue_btn.click(make_wangp_queue, inputs=[project_state, queue_scope],
                                    outputs=[queue_status, queue_file])

                with gr.Row():
                    out_folder = gr.Textbox(label="WanGP output 폴더", value=_out0, scale=3)
                    open_folder_btn = gr.Button("📂 폴더 열기", scale=1)

                with gr.Row():
                    launch_pinokio_btn = gr.Button("🚀 Pinokio 실행", variant="secondary")
                    kill_ollama_btn = gr.Button("🛑 Ollama 프로세스 종료 (VRAM 확보)", variant="stop")

                with gr.Row():
                    watch_start_btn = gr.Button("👀 영상 감시 시작", variant="primary")
                    watch_stop_btn = gr.Button("⏸️ 감시 중지")
                watch_status = gr.Markdown()
                watch_timer = gr.Timer(3.0, active=False)

                cur_video = gr.Video(label="현재 컷 영상 미리보기", interactive=False)
                gr.Markdown("자동으로 못 찾았다면, 직접 영상 파일을 골라 현재 컷에 연결할 수 있어요.")
                pick_file = gr.File(label="직접 영상 파일 선택", file_types=[".mp4"],
                                    type="filepath", file_count="multiple")
                vid_summary = gr.Markdown()

                # 이벤트 연결
                refresh_vid_btn.click(
                    refresh_video, inputs=[project_state],
                    outputs=[cur_shot_dd, cur_prompt, cur_negative, cur_video, vid_summary],
                )
                cur_shot_dd.change(
                    on_cur_shot_change, inputs=[project_state, cur_shot_dd],
                    outputs=[cur_prompt, cur_negative, cur_video],
                )
                open_folder_btn.click(open_wangp_folder, inputs=[out_folder], outputs=[watch_status])
                launch_pinokio_btn.click(launch_pinokio_ui, outputs=[watch_status])
                kill_ollama_btn.click(kill_ollama_process_ui, outputs=[watch_status])
                watch_start_btn.click(
                    start_watch, inputs=[project_state, out_folder],
                    outputs=[watch_known, watch_timer, watch_status],
                )
                watch_stop_btn.click(stop_watch, outputs=[watch_timer, watch_status])
                watch_timer.tick(
                    on_tick, inputs=[project_state, out_folder, watch_known, cur_shot_dd],
                    outputs=[watch_known, watch_status, cur_shot_dd,
                             cur_prompt, cur_negative, cur_video, vid_summary],
                )
                pick_file.upload(
                    pick_file_assign, inputs=[project_state, pick_file, cur_shot_dd],
                    outputs=[cur_shot_dd, cur_prompt, cur_negative, cur_video,
                             vid_summary, watch_status],
                )

            # ── 탭 5: 최종 출력 ───────────────────────────
            with gr.Tab("🏁 최종 출력", id="final"):
                gr.Markdown("준비된 컷을 합쳐 9:16 세로 영상(`final.mp4`)을 만듭니다.")
                refresh_final_btn = gr.Button("🔄 현황 새로고침")
                final_status_md = gr.Markdown()

                with gr.Row():
                    final_sub = gr.Checkbox(label="자막 넣기", value=True)
                    final_audio = gr.Checkbox(label="나레이션(음성) 넣기", value=True)
                final_mode = gr.Radio(
                    [FINAL_MODE_READY, FINAL_MODE_BLACK],
                    value=FINAL_MODE_READY, label="누락 컷 처리",
                )

                make_final_btn = gr.Button("🎬 최종 영상 만들기", variant="primary", size="lg")
                final_status2 = gr.Markdown()
                final_video = gr.Video(label="완성된 영상", interactive=False)
                open_result_btn = gr.Button("📂 결과 폴더 열기")
                open_result_md = gr.Markdown()

                refresh_final_btn.click(final_status, inputs=[project_state], outputs=[final_status_md])
                make_final_btn.click(
                    make_final,
                    inputs=[project_state, final_sub, final_audio, final_mode],
                    outputs=[final_status2, final_video],
                )
                open_result_btn.click(open_result, inputs=[project_state], outputs=[open_result_md])

            # ── 탭 6: 진단 / 설정 (Phase 7+8) ─────────────
            with gr.Tab("⚙️ 진단/설정", id="settings"):
                try:
                    _c = config_loader.load_config()
                except Exception:  # noqa: BLE001
                    _c = config_loader.DEFAULTS

                gr.Markdown("문제가 생기면 여기서 점검하고 고칠 수 있어요.")
                diag_btn = gr.Button("🔍 전체 진단", variant="primary")
                diag_out = gr.Markdown()
                diag_btn.click(run_full_diagnostics, outputs=diag_out)

                gr.Markdown("#### 🧠 Qwen 모델")
                with gr.Row():
                    model_dd = gr.Dropdown(choices=get_installed_models(),
                                           value=_c.get("ollama_model"),
                                           label="설치된 모델", scale=3)
                    model_refresh = gr.Button("🔄 새로고침", scale=1)
                    model_save = gr.Button("이 모델 사용", scale=1)
                model_status = gr.Markdown()
                model_refresh.click(lambda: gr.update(choices=get_installed_models()),
                                    outputs=model_dd)
                model_save.click(save_model, inputs=[model_dd], outputs=[model_status])

                gr.Markdown("#### 📁 경로 다시 지정")
                wan_in = gr.Textbox(label="WanGP output 폴더", value=_c.get("wan_gp_output_path", ""))
                sup_in = gr.Textbox(label="Supertonic3 home 폴더", value=_c.get("supertonic_home", ""))
                ff_in = gr.Textbox(label="ffmpeg 경로", value=_c.get("ffmpeg_path", "ffmpeg"))
                path_save = gr.Button("💾 경로 저장")
                path_status = gr.Markdown()
                path_save.click(save_paths, inputs=[wan_in, sup_in, ff_in], outputs=[path_status])

                gr.Markdown("#### 🎞️ 영상 설정")
                with gr.Row():
                    fps_in = gr.Number(label="FPS", value=_c.get("default_fps", 24))
                    frames_in = gr.Number(label="프레임 수", value=_c.get("default_frames_per_shot", 141))
                    res_in = gr.Textbox(label="해상도", value=_c.get("test_resolution", "512x320"))
                vs_save = gr.Button("💾 영상 설정 저장")
                vs_status = gr.Markdown()
                vs_save.click(save_video_settings, inputs=[fps_in, frames_in, res_in], outputs=[vs_status])

                gr.Markdown("---\n### 🛠️ 전문가 모드")
                expert_chk = gr.Checkbox(label="전문가 모드 켜기 (JSON·로그 보기)", value=False)
                with gr.Group(visible=False) as expert_group:
                    gr.Markdown("현재 이어하기한 프로젝트의 파일과 로그를 봅니다.")
                    with gr.Row():
                        file_dd = gr.Dropdown(label="프로젝트 파일", choices=[], scale=3)
                        file_refresh = gr.Button("🔄 파일 목록", scale=1)
                    file_view = gr.Code(label="파일 내용")
                    with gr.Row():
                        log_dd = gr.Dropdown(label="로그", choices=[], scale=3)
                        log_refresh = gr.Button("🔄 로그 목록", scale=1)
                    log_view = gr.Textbox(label="로그 내용", lines=12, interactive=False)

                expert_chk.change(lambda v: gr.update(visible=v),
                                  inputs=[expert_chk], outputs=[expert_group])
                file_refresh.click(list_project_files, inputs=[project_state], outputs=[file_dd])
                file_dd.change(view_file, inputs=[project_state, file_dd], outputs=[file_view])
                log_refresh.click(list_log_files, inputs=[project_state], outputs=[log_dd])
                log_dd.change(view_log, inputs=[project_state, log_dd], outputs=[log_view])

        # ── 시작/이어하기 이벤트 (tabs 정의 후 등록: 탭 전환 출력 필요) ──
        refresh_proj_btn.click(refresh_projects, outputs=[project_dd])
        resume_btn.click(
            resume_project, inputs=[project_dd],
            outputs=[project_state, shots_state, tts_state, start_status, main_tabs],
        ).then(
            refresh_lab_ui, inputs=[project_state], outputs=[lab_shot_dd]
        )
        new_btn.click(
            start_new,
            outputs=[project_state, shots_state, tts_state, start_status, main_tabs],
        ).then(
            refresh_lab_ui, inputs=[project_state], outputs=[lab_shot_dd]
        )
        delete_btn.click(
            delete_project_ui, inputs=[project_dd, project_state],
            outputs=[project_state, project_dd, start_status],
        )
        make_btn.click(
            analyze,
            inputs=[title_in, script_in, mode_in, dur_in, dur_custom],
            outputs=[make_status, shots_state, project_state],
        ).then(
            refresh_lab_ui, inputs=[project_state], outputs=[lab_shot_dd]
        )

    return demo


if __name__ == "__main__":
    try:
        _cfg = config_loader.load_config()
        _allowed = [os.path.abspath(_cfg["project_root"])]
    except Exception:  # noqa: BLE001
        _allowed = []
    build_ui().launch(theme=gr.themes.Soft(), allowed_paths=_allowed)
