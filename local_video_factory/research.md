# research.md — Local Video Factory 아키텍처/인수인계 문서

> 목적: 다른 코딩 에이전트(또는 개발자)가 이 문서만 읽고도 전체 구조·데이터 흐름·외부
> 연동·관례·함정을 즉시 파악하고, 아키텍처 변경/유지보수를 바로 이어갈 수 있게 한다.
> 모든 내용은 실제 코드(`C:\Users\petbl\allin\local_video_factory`) 기준이며 검증된 사실이다.

---

## 0. 한 줄 정의

`Local Video Factory` = **완전 로컬·무료** 쇼츠/영상 자동화 프로그램.
대본/아이디어 입력 → AI가 **6초 이하 컷**으로 분해 → 컷별 (영어 영상 프롬프트 · 한국어
나레이션 TTS · 자막) 생성 → WanGP/LTX2로 컷 영상 생성 → ffmpeg로 **9:16 `final.mp4`** 조립.

설계 1순위는 **사용자 경험**(초보자도 버튼 몇 개로). 기술 용어/JSON/로그는 전문가 모드에 숨긴다.

---

## 1. 빠른 시작

```powershell
cd C:\Users\petbl\allin\local_video_factory
pip install -r requirements.txt        # requests, PyYAML, gradio>=5 (개발검증 6.15.2)

# CLI (UI 없이 대본→컷→프롬프트)
python app_cli.py check                # 환경 점검
python app_cli.py make --title "비 오는 날 모찌" --mode mochi --duration 15 --script-file sample_script.txt

# 브라우저 UI (전체 기능)
python app_gradio.py                   # http://127.0.0.1:7860
```

- Python 3.13, Windows 11. 외부 유료 API/SDK 전혀 없음.
- 산출물은 전부 `projects/<YYYY-MM-DD_제목>/` 에 저장 → 껐다 켜도 이어하기 가능.

---

## 2. 절대 규칙 (문서 00~03에서 유래, 코드로 강제됨)

1. 외부 유료 API 금지 (OpenAI/Runway/Luma/Kling/OpenRouter 등). LM Studio·Gemma 금지.
2. LLM은 **Ollama + Qwen3.5 9B 하나만** (`qwen3.5-9b-local:latest`).
3. 영상 생성은 **Pinokio WanGP/LTX2**. 초기엔 반자동(프롬프트/큐 + 폴더 감시), 완전 자동 호출은 후순위.
4. TTS는 **Supertonic3**(로컬). 후처리는 **ffmpeg**.
5. 모든 영상은 6초 이하 컷으로 분해.
6. 프로젝트 폴더 밖 파일 수정 금지(코드로 차단), 삭제/업로드 기본 금지.
7. 초보자 UI 우선, 오류는 로그보다 "쉬운 문장 + 해결 버튼".

> 강제 지점: `config_loader.load_config()`가 `use_lmstudio/use_gemma/use_paid_api/
> use_external_video_mcp`를 강제로 False 처리. `get_installed_models()`가 gemma/lmstudio 모델을
> 선택지에서 제외. `ProjectManager.path()`가 프로젝트 폴더 밖 경로를 차단.

---

## 3. 폴더 구조와 파일별 역할

```
local_video_factory/
├── config.yaml              # 전역 설정 (경로/모델/기본값/안전장치)
├── requirements.txt
├── app_cli.py               # CLI 진입점: check / make
├── app_gradio.py            # Gradio 7탭 UI (전체 기능 오케스트레이션)
├── sample_script.txt        # 테스트용 대본
├── README.md
├── research.md              # (이 문서)
│
├── core/                    # 기반 모듈 (UI/외부도구 의존 없음)
│   ├── config_loader.py     # config.yaml 로딩/검증/저장(주석보존)
│   ├── llm_client.py        # Ollama /api/chat 호출, JSON 강제, 서버/모델 점검, unload
│   ├── validate_json.py     # LLM JSON 코드블록 제거/복구/스키마 검증
│   └── project_manager.py   # 프로젝트 폴더·project.json·status.json, 목록/이어하기
│
├── skills/                  # 대본분석 → 컷분해 → 프롬프트 생성 + LTX-2 강화 + 품질점수 + WanGP/Deepy 팩
│   ├── _common.py           # 프롬프트 템플릿 로딩 + 스타일 컨텍스트 매핑
│   ├── script_parser_skill.py   # 대본 → script_segments.json  (LLM)
│   ├── shot_planner_skill.py     # segments → shots.json (6초 컷, 타이밍은 코드가 결정) (LLM)
│   ├── prompt_director_skill.py  # shots → prompt_XXX.txt + negative_prompt.txt (LLM, 1회 배치) + 규칙기반 품질채점 + Deepy팩
│   ├── ltx_prompt_enhancer_skill.py  # LTX-2 특화 프롬프트 강화 (LLM, 연구소 탭 전용)
│   ├── prompt_quality_score.py       # 프롬프트 품질 6항목 규칙 채점 (LLM 없음)
│   ├── wangp_deepy_bridge_skill.py   # WanGP/Deepy JSON팩 + 배치 md 생성 (LLM 없음)
│   ├── supertonic_tts_skill.py   # 컷별 나레이션 → audio/audio_XXX.wav (제너레이터)
│   ├── timeline_builder_skill.py # 영상/음성 길이 정렬 → timeline.json (+길이초과 경고)
│   └── subtitle_sync_skill.py    # → captions.srt (UTF-8-SIG)
│
├── tools/                   # 외부 프로세스/시스템 연동
│   ├── supertonic_engine.py # Supertonic3 어댑터 (HTTP 우선, CLI 폴백)
│   ├── watcher.py           # WanGP output 폴더 감시 → shot_XXX.mp4 연결
│   ├── ffmpeg_tools.py      # 9:16 클립 정규화 → concat → 자막 번인 → final.mp4
│   └── wangp_queue.py       # WanGP Load Queue용 queue.zip 생성 (템플릿 복제)
│
├── prompts/                 # LLM 시스템/스타일 프롬프트(.md) — 코드 아님, 텍스트 자산
│   ├── system_director.md   # 공통 시스템 프롬프트(항상 JSON만 출력하도록)
│   ├── script_parser.md     # script_parser 작업 지시
│   ├── shot_planner.md       # shot_planner 작업 지시
│   ├── wangp_ltx2_prompt_template.md  # 영어 영상 프롬프트 생성 지시
│   └── style_*.md           # 스타일 프리셋(mochi/product_cf/info/emotional/senior_trot)
│                            #   각 파일에 "Default negative prompt:" 줄 포함 → negative 추출
│
└── projects/                # 산출물 (실행 중 생성)
    └── <YYYY-MM-DD_제목>/
        ├── project.json idea.txt script_original.txt
        ├── script_segments.json shots.json timeline.json status.json
        ├── prompt_001.txt ... negative_prompt.txt captions.srt
        ├── wangp_queue.zip wangp_queue.json   (큐 생성 시)
        ├── wangp_deepy_pack_NNN.json wangp_prompt_NNN.txt wangp_batch_prompts.md  (Deepy 팩)
        ├── audio/  audio_001.wav ...
        ├── outputs/ shot_001.mp4 ... final.mp4  (_clips/ 는 합성 중 임시, 자동삭제)
        └── logs/   ollama.log tts.log watcher.log ffmpeg.log error.log
```

계층 의존 방향: `app_*` → `skills` → `tools`/`core`. `core`는 다른 계층에 의존하지 않음.

---

## 4. 전체 파이프라인 (데이터 흐름)

```
대본/아이디어
  │  (script_parser_skill, Ollama)
  ▼ script_segments.json   {segments:[{segment_id,sentence,meaning,emotion,keywords,visual_potential,tts_text}]}
  │  (shot_planner_skill, Ollama + 코드 타이밍)
  ▼ shots.json             {shots:[{shot_number,duration,korean_description,keywords,camera,lighting,motion,
  │                                  english_video_prompt,negative_prompt,tts_text,tts_file,video_file,status,...}]}
  │  (prompt_director_skill, Ollama 1회 배치)
  ▼ prompt_001.txt..., negative_prompt.txt   (+ shots.english_video_prompt 채움, status=prompt_ready)
  │  (supertonic_tts_skill → Supertonic3)
  ▼ audio/audio_XXX.wav    (+ shots.tts_duration/tts_status)
  │  (timeline_builder_skill)
  ▼ timeline.json          {shots:[{start,end,used_duration,video_duration,tts_duration,over_limit}],warnings:[]}
  │  (subtitle_sync_skill)
  ▼ captions.srt           (UTF-8-SIG, used_duration 기반 타이밍)
  │  (wangp_queue.build_queue → 사용자가 WanGP Load Queue → Generate)
  │  (watcher: output 폴더 감시 → 새 mp4 → outputs/shot_XXX.mp4)
  ▼ shots.video_file 채움 (status=video_ready)
  │  (ffmpeg_tools.build_final)
  ▼ outputs/final.mp4      (9:16, 720x1280, h264, AAC, 자막 번인)
```

**핵심 단일 진실원천(SSOT):** `shots.json`. 모든 단계가 이걸 읽고/갱신한다.
`status.json`은 UI 진행상태/이어하기용 별도 파일.

**중요한 설계 결정:** 타이밍·파일명·번호는 **LLM이 아니라 코드가 결정**한다(LLM 출력이
흔들려도 깨지지 않게). 컷 영상 길이 = `frames_per_shot/fps` = 141/24 ≈ **5.875초** 고정.

---

## 5. 데이터 스키마 (실제 생성 예)

### project.json
```json
{"project_id","project_title","created_at","updated_at","input_mode","style_preset",
 "target_duration","max_shot_duration","fps","frames_per_shot","resolution","final_aspect_ratio"}
```

### status.json  (project_manager.update_status 가 생성)
```json
{"project_id","current_status","user_status_message","progress","current_step","total_steps",
 "current_shot","total_shots","missing_items":{"videos":[],"audio":[],"subtitles":[]},
 "last_error","can_resume","updated_at"}
```
- `current_status` 내부값 → `user_status_message`는 `project_manager.STATUS_MESSAGES`로 매핑.
- 진행률은 `STEP_ORDER`(7단계) 기준. `TOTAL_STEPS=7`.

### shots.json (컷 1개의 필드)
```
shot_number, chapter_id, start_time, end_time, duration, source_sentences[],
korean_description, keywords[], emotion, camera, lighting, motion,
english_video_prompt, negative_prompt, tts_text, tts_file, subtitle_ko, video_file, status
(+ TTS 후) tts_duration, tts_voice, tts_status
```
- `status` 값: `planned` → `prompt_ready` → (`video_ready`). TTS는 `tts_status`(ready/failed/skipped).

### timeline.json
```
{fps, video_duration_per_shot, max_shot_duration, total_duration,
 shots:[{shot_number, video_duration, tts_duration, used_duration, start, end, over_limit}],
 warnings:[{shot_number, tts_duration, max_shot_duration, message, options[]}]}
```
- `used_duration` = tts_duration(있으면) else video_duration. 자막/합성 타이밍의 기준.
- `over_limit` = 나레이션이 컷 최대 길이(기본 6초)보다 김 → UI가 해결옵션 안내.

### wangp_queue.zip  (WanGP "Load Queue"가 먹는 포맷)
```
zip 내부에 queue.json = [{"id":<int>, "params":{... WanGP task params ...}}]
```
- `params`는 **검증된 템플릿 task를 그대로 복제**하고 `prompt/negative_prompt/seed/id`만 교체.
  (모델/해상도/스텝 등은 템플릿 값 유지 → 반드시 로드·생성되도록)

---

## 6. 모듈 상세 (공개 함수 시그니처 = 변경 시 영향 지점)

### core/config_loader.py
- `load_config(path=None) -> dict` : 없으면 패키지 루트 config.yaml. `DEFAULTS` 병합, 금지옵션 강제 off,
  `cfg["warnings"]`/`cfg["_config_path"]` 부가. 실패 시 `ConfigError`(사용자용 문장).
- `update_config_values(updates: dict, path=None)` : **주석 보존** 라인 치환으로 최상위 스칼라 키 저장(없으면 추가).
- `DEFAULTS` : 모든 설정 키 기본값(여기에 키 추가해야 누락 시 안전).

### core/llm_client.py  (Ollama 전용)
- `check_server(cfg)->(ok,msg)`, `list_models(cfg)->[name]`, `ensure_model(cfg)->(ok,msg,available)`.
- `chat(cfg, system, user, *, force_json=True, log_path=None)->str` : `/api/chat`, stream=false,
  `format:"json"` 강제(파싱 안정), 코드블록 제거. 실패 시 `LLMError(message, code, detail)`
  (code: server_down/model_missing/timeout/bad_json/unknown).
- `chat_json(cfg, system, user, *, log_path=None)->dict` : chat + `validate_json.loads_with_repair`.
- `unload_model(cfg)->bool` : `keep_alive:0`로 VRAM 해제(영상 생성 전 충돌 완화).

### core/validate_json.py
- `strip_code_fences(text)`, `loads_with_repair(raw)`(균형괄호 추출/끝쉼표 제거 등 복구),
  `validate_segments(data)`, `validate_shots(data)`(누락필드 기본값). 실패 시 `JSONRepairError`.

### core/project_manager.py
- `slugify(title)` : Windows 안전 폴더명(금지문자 제거, 예약어 회피, 60자 제한).
- `create_project(root,title,*,input_mode,style_preset,target_duration,cfg)->ProjectManager`
  (동명 폴더는 _2,_3 자동 증가; ensure_dirs; project.json/status.json 초기화).
- `ProjectManager`: `.dir/.path(*parts)/.audio_dir/.outputs_dir/.logs_dir`,
  `.save_json/.load_json/.save_text(name,text,bom=False)/.exists/.update_status(...)`.
  **`.path()`는 프로젝트 폴더 밖 경로를 ValueError로 차단(안전장치).**
- `list_projects(root)->[{project_id,title,created_at,target_duration,progress,status_message,has_final}]` (최신순).
- `STATUS_MESSAGES`(내부상태→한국어), `STEP_ORDER`, `TOTAL_STEPS`.

### skills/_common.py
- `load_prompt(name)`(prompts/ 읽기), `style_context(input_mode,style_preset)`(스타일 .md 텍스트),
  `negative_prompt_for(...)`(스타일 .md의 "Default negative prompt:" 줄 추출), `STYLE_FILES` 매핑.
- ⚠️ 프롬프트 템플릿은 JSON 예시의 `{}`를 포함하므로 `str.format` 금지 → **`.replace("{key}", ...)`** 로 치환한다.

### skills (각 단계, 반환=정규화 dict, 부수효과=파일 저장)
- `script_parser_skill.parse_script(cfg,pm,project,script_text)->segments_data` (저장: script_segments.json)
- `shot_planner_skill.plan_shots(cfg,pm,project,segments_data)->shots_data` (저장: shots.json)
  - 컷수 ≈ target_duration/shot_seconds. 타이밍·파일경로·번호는 코드가 채움. 빈 설명은 키워드/나레이션으로 보강.
- `prompt_director_skill.generate_prompts(cfg,pm,project,shots_data)->shots_data`
  - **LLM 1회 배치**로 전 컷 영어 프롬프트. 실패/누락 시 컷 필드로 백업 프롬프트 조립(작업 안 멈춤). 저장: prompt_XXX.txt, negative_prompt.txt.
- `supertonic_tts_skill.synthesize_all(cfg,pm,project,shots_data,voice="")` **제너레이터**:
  `("progress",i,total,num)` / `("shot_done",num,dur,ok)` / `("done",summary)`. 개별 컷 실패는 건너뜀.
- `timeline_builder_skill.build_timeline(cfg,pm,project,shots_data)->timeline`
- `subtitle_sync_skill.build_srt(pm,shots_data,timeline)->srt_text` (UTF-8-SIG로 captions.srt 저장)

### tools/supertonic_engine.py  (Supertonic3 어댑터)
- `probe(cfg)->{available,server_ok,cli_ok,server_url,python_path,cli_path,message}`
- `synthesize(cfg,text,output_path,*,voice="",status=None)->{path,duration,sample_rate,invocation,voice}`
  - **HTTP 서버(포트 3093) 우선, 없으면 venv CLI 폴백**. 실패 시 `TTSError`.
- 호출 규약(중요):
  - CLI: `<home>/supertonic3-local-tts/.venv-win/Scripts/python.exe  src/supertonic3_cli.py
    --input in.txt --output out.wav --model supertonic-3 --voice F1 --lang ko --speed 1.05
    --total-step 8 --silence-duration 0.3 --json`
  - HTTP: `GET {url}/health`→{ok:true}, `POST {url}/api/tts {text,voice,model,lang,speed,total_step,silence_duration}`→{ok,path}
  - 목소리: M1~M5(남), F1~F5(여). 기본 F1.

### tools/watcher.py  (WanGP output 감시)
- `snapshot(folder)->[paths]`(감시 시작 기준선), `find_new_stable(folder,known,min_age=2.0)->[새 안정 파일]`
  (mtime이 2초 이상 안 변하면 "생성 완료"로 판단 — 폴링 친화), `import_video/assign_to_shot`,
  `shots_missing_video/next_missing_shot`, `open_folder`.
- WanGP 파일명은 타임스탬프 기반(`2026-..._seed..._prompt.mp4`)이라 **내용 매칭 불가** →
  "감시 시작 이후 새로 나타난 영상을 빈 컷 순서대로 연결" 방식.

### tools/ffmpeg_tools.py  (최종 합성)
- `check_ffmpeg(cfg)->(ok,msg)`, `missing_check(pm,shots_data)->{...}`(누락 검사),
  `build_final(cfg,pm,project,shots_data,timeline,*,include,with_audio,with_subtitles,black_for_missing)`
  **제너레이터**: `("progress",i,total,msg)` / `("done",result)`.
- 처리: 컷마다 9:16 캔버스(`CANVAS_W×CANVAS_H=720×1280`)로 정규화(scale+pad+tpad freeze, apad) →
  concat 데먹서 → captions.srt 번인(맑은고딕, **cwd=프로젝트폴더로 두고 상대경로 'captions.srt'**로 Windows 경로 이스케이프 회피).
- 인코더: `_probe_encoder`가 nvenc 기능테스트 → 실패 시 **libx264 폴백**(`_rebuild_with_libx264`).

### tools/wangp_queue.py  (WanGP Load Queue 자동화)
- `load_template_task(cfg)->{"id","params"}` : 템플릿을 정규화(`_normalize_to_task`가 queue.zip/queue.json/
  단일 settings dict 허용, 단 **params에 model_type 필수**).
- `build_queue(cfg,pm,project,shots_data,*,only_shots=None)->(zip_path,count)` : 템플릿 복제+프롬프트 교체.
- 템플릿 경로: `config.wan_gp_queue_template` → 없으면 `<wan_gp_path>/small_moments_queue/queue.json` 자동탐지.

---

## 7. Gradio UI 구조 (app_gradio.py)

- `build_ui()->gr.Blocks`. 상단: 인트로 + "환경 점검" 아코디언. 본문은 `with gr.Tabs() as main_tabs:`.
- **States**: `shots_state`(컷 보드용 list), `project_state`(현재 project_id), `tts_state`(음성 미리듣기 list),
  탭4의 `watch_known`(감시 기준선).
- **탭(id)**: `start`(시작/이어하기) · `make`(만들기) · `board`(컷 보드) · `prompt_lab`(프롬프트 연구소) · `audio`(음성/자막) · `video`(영상 생성) · `final`(최종 출력) · `settings`(진단/설정).
- 동적 카드/오디오/영상 미리보기는 `@gr.render(inputs=[state])`로 렌더(상태 변경 시 재렌더).
- 긴 작업은 **제너레이터 콜백**으로 진행률 yield. 진행 중 미변경 출력은 `gr.skip()`.
- 탭 전환은 콜백이 `gr.Tabs(selected="board")` 반환(시작 탭의 이어하기/새 영상). 시작탭 이벤트는
  탭 정의가 끝난 뒤(= `main_tabs` 클로즈 후) 등록한다.
- 로컬 wav/mp4 재생을 위해 `launch(allowed_paths=[projects 절대경로])`.

주요 backend 함수(콜백):
- 만들기: `analyze(title,script,mode,dur,custom)` 제너레이터 → (status_md, shots_state, project_state)
- 음성: `check_tts_engine()`, `make_tts(project_id,voice)` 제너레이터 → (status, tts_state, srt_box)
- 영상: `refresh_video/on_cur_shot_change/start_watch/stop_watch/on_tick/pick_file_assign/open_wangp_folder/make_wangp_queue`
  - `on_tick`은 `gr.Timer(3.0)`의 tick에 연결(감시 폴링).
- 프롬프트 연구소: `refresh_lab_ui/on_lab_shot_change/enhance_single_prompt_ui/save_lab_prompt_ui/save_to_library_ui`
  - `enhance_single_prompt_ui`는 LLM 호출(연구소 탭 전용). 주 파이프라인(`generate_prompts`)에서는 LLM 호출 없이 구칙 기반 품질점수+Deepy팩만 실행.
- 최종: `final_status/make_final(gen)/open_result`
- 진단/설정: `run_full_diagnostics/get_installed_models/save_model/save_paths/save_video_settings`
  + 전문가 뷰어 `list_project_files/view_file/list_log_files/view_log`
- 시작: `list_project_choices/refresh_projects/resume_project/start_new`

---

## 8. 외부 연동 사실 (실측, 변경 가능성 있는 환경 값)

| 도구 | 위치/포트 | 호출 방식 |
|---|---|---|
| Ollama | `http://localhost:11434` | `/api/chat`(생성), `/api/tags`(모델목록), `/api/generate keep_alive:0`(unload). 모델 `qwen3.5-9b-local:latest` |
| Supertonic3 | home=`C:\Users\petbl\supertonic3-local-tts-20260517-r4`, HTTP `127.0.0.1:3093` | HTTP `/api/tts` 우선, 없으면 venv CLI. (참고 구현: `C:\Users\petbl\newauto\app\services\supertonic3_*.py`) |
| WanGP/Wan2GP | 앱 `C:\pinokio\api\wan.git\app`, output `...\app\outputs`, **포트 동적**(Pinokio `start.js`의 `kernel.port()`; env `SERVER_PORT`) | 반자동: 큐파일 Load Queue / 프롬프트 복붙 + 폴더 감시. 직접 기동: `app/env/Scripts/python.exe wgp.py --multiple-images` (env SERVER_PORT) |
| ffmpeg/ffprobe | PATH (`ffmpeg`,`ffprobe`) | subprocess |

WanGP 세부(자동화 조사 결과):
- `wgp.py`(726KB)에 **api_name 없음** + 큐+gr.State 기반 → gradio_client 완전자동 호출은 취약 → **불채택**.
- 채택: **Save/Load Queue**. queue.zip 안 queue.json. "Load Queue"는 UI 하단 **"Queue Management" 접힌 아코디언** 안.
- 우리 queue.zip 로드 성공 **실증됨**(WanGP가 우리 task 3개를 자체 큐/`error_queue.zip`에 그대로 보존).
- `settings/*.json`에는 **model_type이 없음**(UI 선택 모델로 채움) → 단독 템플릿 불가, **Save Queue 결과만 유효**.

---

## 9. config.yaml 키 (핵심)

```
ollama_model/ollama_base_url/ollama_chat_endpoint/ollama_timeout/ollama_temperature/ollama_top_p/ollama_unload_after_run
use_lmstudio/use_gemma/use_paid_api/use_external_video_mcp   # 모두 false 고정(코드가 강제)
default_max_shot_seconds=6 / default_shot_seconds=5 / default_frames_per_shot=141 / default_fps=24
test_resolution="512x320" / final_aspect_ratio="9:16"
wan_gp_path / wan_gp_output_path / wan_gp_queue_template
supertonic_home/host/port/model/lang/speed/total_step/silence_duration/default_voice
ffmpeg_path / ffprobe_path / project_root
allowed_commands[] / blocked_commands[]                      # 안전 whitelist (문서 08)
```
- 키 추가 시 **`config_loader.DEFAULTS`에도 기본값 추가**(누락 방지).

---

## 10. 알려진 함정 / 환경 의존 (꼭 알아둘 것)

1. **Gradio 6 API 변경**:
   - `gr.Textbox`는 `show_copy_button` 없음 → **`buttons=["copy"]`**.
   - `theme`는 `gr.Blocks(...)`가 아니라 **`launch(theme=...)`** 로 전달.
   - 이런 오류는 `@gr.render` 내부 컴포넌트면 **빌드 시 안 잡히고 런타임에만** 터진다 → 렌더 콜백 변경 시 실제 실행 검증 필요.
2. **Windows PowerShell 5.1 파이프 인코딩**: 한글을 stdin 파이프로 넘기면 `?`로 깨진다($OutputEncoding=ASCII).
   → CLI는 `--script`/`--script-file` 권장(둘 다 안전). app_cli는 stdio를 UTF-8로 reconfigure하고 깨짐 감지 경고.
3. **VRAM 8GB(RTX 4060)**: WanGP 22B + 832×480 생성은 **CUDA OOM** 발생. 대응: 더 가벼운 해상도/모델,
   오프로딩, 1컷씩, 그리고 `llm_client.unload_model`로 Ollama VRAM 해제. (Ollama는 평소 VRAM 점유 안 함이 확인됨)
4. **nvenc**: 이 환경의 ffmpeg는 nvenc 기능테스트 실패 → libx264 자동 폴백(정상). nvenc 강제 금지.
5. **자막 경로**: ffmpeg subtitles 필터의 Windows 경로 이스케이프가 까다로워, **cwd=프로젝트폴더 + 상대경로 'captions.srt'** 로 우회.
6. **나레이션 길이**: 현재 shot_planner가 컷당 1~2문장을 묶어 나레이션이 6초 컷보다 길어지는 경향(over_limit 경고로 처리).
   개선 여지: "컷당 1문장 우선 + 길면 분할".
7. **브라우저 자동화(Claude in Chrome / Preview)**: 이 세션에서 간헐적으로 연결 실패/타임아웃. UI 검증은 build_ui 빌드 + 콜백 직접 구동 + 스크린샷 조합으로 수행.

---

## 11. 확장 가이드 (자주 하는 변경의 패턴)

- **새 파이프라인 단계 추가**: `skills/`에 `xxx_skill.py` 추가(입력=cfg,pm,project,상위데이터 / 출력=정규화 dict +
  파일 저장). 긴 작업이면 제너레이터로 진행률 yield. `shots.json`에 필드 추가 시 `validate_json.validate_shots`에 기본값 등록.
- **새 탭 추가**: `app_gradio.build_ui` 안 `main_tabs`에 `with gr.Tab("...", id="..."):`. 동적 목록은 `@gr.render`.
  백엔드는 build_ui 밖 모듈 함수로 두고 `.click/.change`로 연결.
- **TTS 엔진 교체/추가**: `tools/supertonic_engine.py`의 `probe/synthesize` 인터페이스를 맞춘 새 어댑터 작성 →
  `supertonic_tts_skill`이 엔진만 바꿔 끼우면 됨.
- **영상 생성 백엔드 변경**: watcher(폴더 감시) / wangp_queue(큐) 두 경로가 독립. 다른 생성기를 붙이면
  `assign_to_shot`로 컷에 mp4를 연결하는 계약만 지키면 ffmpeg 합성은 그대로 동작.
- **설정 키 추가**: config.yaml + `config_loader.DEFAULTS`. UI에서 저장하려면 `update_config_values` 사용.

---

## 12. 구현/검증 현황 (Phase 1~8 완료 + WanGP 큐)

| Phase | 내용 | 상태 | 검증 방식 |
|---|---|---|---|
| 1 | CLI: 대본→컷→prompt txt | ✅ | 샘플 대본 실행, JSON 무결성 |
| 2 | Gradio 만들기/컷 보드 | ✅ | 빌드+analyze 제너레이터+스크린샷 |
| 3 | Supertonic3 TTS + 자막 | ✅ | wav 3개 생성, timeline/srt, 길이초과 경고 |
| 4 | WanGP 감시·자동 연결 | ✅ | watcher import/assign, on_tick 자동 연결 |
| 5 | ffmpeg 9:16 final.mp4 | ✅ | ffprobe: 720x1280/h264/AAC/~20.8s |
| 6 | 저장/이어하기 | ✅ | list_projects, resume_project 상태 복원+탭전환 |
| 7+8 | 진단/설정·전문가 모드 | ✅ | 진단 출력, config 저장 왕복, 파일/로그 뷰어 |
| — | WanGP 큐 자동화 | ✅(로드 실증) | WanGP 실기동, Load Queue로 우리 zip 수용 확인 |

**미완/다음 작업 후보:**
- 8GB VRAM에 맞는 WanGP 큐 템플릿 확정(사용자가 Save Queue한 파일을 `wan_gp_queue_template`에 지정 → 그 설정 복제). **진행 중.**
- shot_planner 나레이션-영상 길이 싱크 튜닝(컷당 1문장 우선).
- Electron + FastAPI 데스크톱 앱(문서 Phase 9, 후순위).

---

## 13. 디버깅 진입점

- 환경 점검: `python app_cli.py check` 또는 UI "진단/설정 → 전체 진단"(`run_full_diagnostics`).
- 로그: `projects/<id>/logs/` (ollama/tts/watcher/ffmpeg/error). 전문가 모드에서 열람.
- LLM JSON 깨짐: `validate_json.loads_with_repair`가 1차 복구. `chat`에 `format:"json"`이 강제됨.
- 컷 데이터 직접 확인: `projects/<id>/shots.json`(SSOT), `timeline.json`, `status.json`.

---

## 14. 원천 문서

설계 근거: `C:\Users\petbl\Downloads\local_video_factory_docs_split\local_video_factory_docs\00~08_*.md`
(00 업로드순서/규칙, 01 비전/범위, 02 사용자흐름/UI, 03 스택/아키텍처, 04 스키마/파일,
 05 모듈/스킬/MCP, 06 구현단계, 07 에이전트 지시문, 08 안전/오류/복구).
이 문서(research.md)와 충돌 시 **코드가 우선**(이 문서는 코드 기준으로 작성됨).
