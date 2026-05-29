# 만들기 탭 비주얼 스타일 프리셋 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 Local Video Factory 파이프라인을 깨지 않고, 만들기 탭에 “콘텐츠 목적”과 “비주얼 스타일 프리셋”을 분리한 2-레이어 선택 구조와 컷 전체 스타일 잠금 기능을 추가한다.

**Architecture:** `input_mode`는 콘텐츠 목적 SSOT로 유지하고, `style_preset`은 실제 스타일 컨텍스트를 고르는 키로 유지한다. 스타일 잠금은 `prompt_director_skill.generate_prompts()`가 LLM 배치 프롬프트를 만든 뒤, 저장 직전에 결정론적으로 prefix/negative/Deepy copy fields를 동기화하는 후처리 단계로 붙인다.

**Tech Stack:** Python 3.13, Gradio 6.15.2 호환 UI, Ollama/Qwen3.5 9B, WanGP/LTX2 queue, Supertonic3, ffmpeg, stdlib `unittest`.

---

## 1. 참고한 실제 코드 흐름

- `README.md`: 전체 기능은 Phase 1~8 완료 상태이며 UI 실행은 `python app_gradio.py`, CLI 검증은 `python app_cli.py check`다.
- `research.md`: 외부 유료 API 금지, Ollama + Qwen3.5 9B만 사용, 초보자 UI 우선, `shots.json`이 SSOT, 프로젝트 폴더 밖 파일 수정 금지.
- `skills/_common.py`: `STYLE_FILES`가 스타일 키를 `prompts/style_*.md`로 매핑하고, `style_context()`와 `negative_prompt_for()`가 이 파일을 읽는다.
- `skills/prompt_director_skill.py`: 프롬프트 생성 후 `base_prompt`, `ltx_prompt`, `deepy_prompt_pack`, `prompt_XXX.txt`, `negative_prompt.txt`, `shots.json`을 저장한다. 스타일 잠금은 이 저장 직전에 들어가야 파일들이 모두 같은 값을 보게 된다.
- `skills/wangp_deepy_bridge_skill.py`: `wangp_copy_positive`는 `ltx_prompt`에서 나온다. 따라서 잠금 후 `ltx_prompt`까지 함께 갱신해야 Deepy/WanGP 파일이 자동 반영된다.
- `skills/ltx_prompt_enhancer_skill.py`: 이미 `character_lock_prompt` 인자를 받지만 UI/프로젝트 저장에서 아직 전달되지 않는다.
- `core/project_manager.py`: `create_project()`가 현재 `project.json`에 `input_mode`, `style_preset`까지만 저장한다.
- `app_gradio.py`: `analyze(title, script, mode_label, dur_label, dur_custom)`와 `make_btn.click(inputs=[title_in, script_in, mode_in, dur_in, dur_custom])`의 개수가 정확히 맞아야 한다.

---

## 2. 5.5 의사결정

1. **스타일 잠금은 LLM 프롬프트 템플릿을 바꾸지 않고 후처리로 적용한다.**  
   이유: `prompt_director_skill`의 1회 배치 호출, fallback 프롬프트, 품질점수, Deepy export 흐름을 보존한다.

2. **`style_preset`은 계속 “실제 스타일 파일 키”로 사용하고, 새 `visual_style_preset`은 기록용 메타데이터로 둔다.**  
   이유: 기존 `style_context(input_mode, style_preset)` 계약을 유지하면 `shot_planner_skill`, `prompt_director_skill`, `ltx_prompt_enhancer_skill`이 자연스럽게 새 스타일을 읽는다.

3. **“콘텐츠 목적 자동”은 빈 문자열이 아니라 UI 레이블에서만 존재하고, 저장 시에는 `effective_style = visual_style or mode`로 확정한다.**  
   이유: `project.json`과 `shots.json`에는 항상 `STYLE_FILES`에 있는 키가 들어가야 이어하기와 CLI가 안전하다.

4. **스타일 prefix 파싱은 `Style lock prefix:` 다음의 연속된 들여쓰기 줄만 읽는다.**  
   이유: 기존 스타일 파일은 `Default negative prompt:` 구조를 쓰고 있으며, 새 스타일 파일도 같은 Markdown 규약으로 유지할 수 있다.

5. **새 스타일명은 오타를 정리해 사용한다.**  
   확정 키와 표시명: `anime_3d`(3D 애니 필름), `claymation`(클레이 애니메이션), `lofi_3d_figure`(로파이 3D 피규어), `stickman_sketch`(스틱맨 노트북 낙서), `asmr_cinematic`(ASMR 시네마틱), `neo_closure_vlog`(네오 클로저 브이로그), `retro_8bit`(레트로 8비트), `cyberpunk_neon`(사이버펑크 네온), `minimal_beauty_cf`(미니멀 뷰티 CF), `vlog_illus_self`(브이로그 일러스트 셀프), `wabi_sabi_japan`(와비사비 재팬 리얼).

6. **참조 이미지는 이번 계획에서 UI placeholder로 두지 않는다.**  
   이유: Gradio Image 업로드는 프로젝트 폴더 저장, allowed_paths, 파일 복사 정책, 삭제 정책까지 같이 설계해야 한다. 이번 구현 범위는 스타일 텍스트 잠금과 char lock까지로 자른다.

7. **구버전 프로젝트는 실패시키지 않고 로드 시 setdefault로 보강한다.**  
   이유: 이미 Phase 1~8 산출물이 `projects/`에 존재할 수 있다. 새 필드가 없다는 이유로 이어하기, 연구소 탭, 최종 합성 흐름이 깨지면 안 된다.

8. **알 수 없는 스타일 키는 crash가 아니라 warning + `input_mode` fallback이다.**  
   이유: CLI 직접 입력, 오래된 `project.json`, UI 라벨 변경이 모두 가능한 환경이다. 단, fallback 결과는 `logs/error.log` 또는 `ollama.log`가 아니라 스타일 전용 경고로 추적 가능하게 남긴다.

9. **잠금 적용 후 prompt artifact가 서로 다르면 실패로 본다.**  
   기준: `english_video_prompt`, `negative_prompt`, `ltx_prompt`, `ltx_negative_prompt`, `deepy_prompt_pack.wangp_copy_positive`, `wangp_prompt_XXX.txt`, `prompt_XXX.txt`가 같은 locked positive/negative를 기준으로 생성되어야 한다.

---

## 3. 파일 구조

- Create: `local_video_factory/skills/visual_style_consistency_skill.py`
- Create: `local_video_factory/tests/test_visual_style_consistency.py`
- Create: `local_video_factory/prompts/style_anime_3d.md`
- Create: `local_video_factory/prompts/style_claymation.md`
- Create: `local_video_factory/prompts/style_lofi_3d_figure.md`
- Create: `local_video_factory/prompts/style_stickman_sketch.md`
- Create: `local_video_factory/prompts/style_asmr_cinematic.md`
- Create: `local_video_factory/prompts/style_neo_closure_vlog.md`
- Create: `local_video_factory/prompts/style_retro_8bit.md`
- Create: `local_video_factory/prompts/style_cyberpunk_neon.md`
- Create: `local_video_factory/prompts/style_minimal_beauty_cf.md`
- Create: `local_video_factory/prompts/style_vlog_illus_self.md`
- Create: `local_video_factory/prompts/style_wabi_sabi_japan.md`
- Modify: `local_video_factory/skills/_common.py`
- Modify: `local_video_factory/skills/prompt_director_skill.py`
- Modify: `local_video_factory/skills/ltx_prompt_enhancer_skill.py`
- Modify: `local_video_factory/core/project_manager.py`
- Modify: `local_video_factory/core/validate_json.py`
- Modify: `local_video_factory/app_gradio.py`
- Optional Modify: `local_video_factory/app_cli.py`
- Optional Create: `local_video_factory/core/style_warnings.py` if warning logic becomes noisy inside `_common.py`

---

## 4. Task 1: 스타일 메타데이터와 파서 추가

**Files:**
- Modify: `skills/_common.py`
- Test: `tests/test_visual_style_consistency.py`

- [ ] **Step 1: 실패 테스트 작성**

Create `tests/test_visual_style_consistency.py`:

```python
import unittest

from skills import _common


class StyleCommonTests(unittest.TestCase):
    def test_new_style_file_and_lock_prefix_are_available(self):
        self.assertEqual(_common.style_file_for("CLAYMATION"), "style_claymation.md")
        prefix = _common.style_lock_prefix_for("claymation")
        self.assertTrue(prefix.startswith("claymation style"))
        self.assertLessEqual(len(prefix.split()), 12)

    def test_style_lock_negative_falls_back_to_default_negative(self):
        negative = _common.style_lock_negative_for("claymation")
        self.assertIn("photorealistic", negative)
        self.assertIn("watermark", negative)
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
python -m unittest tests.test_visual_style_consistency -v
```

Expected: FAIL with `AttributeError: module 'skills._common' has no attribute 'style_lock_prefix_for'`.

- [ ] **Step 3: `_common.py` 수정**

Add 11 keys to `STYLE_FILES` and add these helpers below `negative_prompt_for()`:

```python
def _extract_block_after_heading(ctx: str, heading: str) -> str:
    lines = ctx.splitlines()
    collecting = False
    values = []
    for line in lines:
        stripped = line.strip()
        if collecting:
            if not stripped:
                continue
            if stripped.endswith(":") or stripped.lower().startswith("- default negative prompt"):
                break
            values.append(stripped)
            continue
        if heading.lower() in stripped.lower():
            after = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
            if after:
                return after
            collecting = True
    return " ".join(values).strip()


def style_lock_prefix_for(style_preset: str = "", input_mode: str = "") -> str:
    ctx = style_context(input_mode, style_preset)
    return _extract_block_after_heading(ctx, "Style lock prefix")


def style_lock_negative_for(style_preset: str = "", input_mode: str = "") -> str:
    return negative_prompt_for(input_mode, style_preset)
```

If `style_file_for(style_preset)` returns `None`, record a warning string from the caller and use `style_file_for(input_mode)` through existing `style_context()` fallback. Do not raise for unknown user input.

`STYLE_FILES` additions:

```python
    "anime_3d": "style_anime_3d.md",
    "claymation": "style_claymation.md",
    "lofi_3d_figure": "style_lofi_3d_figure.md",
    "stickman_sketch": "style_stickman_sketch.md",
    "asmr_cinematic": "style_asmr_cinematic.md",
    "neo_closure_vlog": "style_neo_closure_vlog.md",
    "retro_8bit": "style_retro_8bit.md",
    "cyberpunk_neon": "style_cyberpunk_neon.md",
    "minimal_beauty_cf": "style_minimal_beauty_cf.md",
    "vlog_illus_self": "style_vlog_illus_self.md",
    "wabi_sabi_japan": "style_wabi_sabi_japan.md",
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
python -m unittest tests.test_visual_style_consistency -v
```

Expected: PASS.

---

## 5. Task 2: 11개 스타일 프롬프트 파일 생성

**Files:**
- Create: `prompts/style_*.md` 11 files
- Test: `tests/test_visual_style_consistency.py`

- [ ] **Step 1: 테스트 보강**

Append:

```python
    def test_every_registered_visual_style_has_file_and_negative_prompt(self):
        keys = [
            "anime_3d", "claymation", "lofi_3d_figure", "stickman_sketch",
            "asmr_cinematic", "neo_closure_vlog", "retro_8bit", "cyberpunk_neon",
            "minimal_beauty_cf", "vlog_illus_self", "wabi_sabi_japan",
        ]
        for key in keys:
            with self.subTest(key=key):
                ctx = _common.style_context("", key)
                self.assertIn("STYLE:", ctx)
                self.assertIn("Style lock prefix", ctx)
                self.assertIn("Default negative prompt", ctx)
                self.assertNotEqual(_common.negative_prompt_for("", key), _common.DEFAULT_NEGATIVE)
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
python -m unittest tests.test_visual_style_consistency -v
```

Expected: FAIL until all 11 prompt files exist.

- [ ] **Step 3: 스타일 파일 작성**

Create each file with this exact structure. Keep every `Style lock prefix` within about 12 words.

`prompts/style_claymation.md`:

```markdown
STYLE: Claymation stop-motion.

- Mood: warm, tactile, playful, handmade.
- Visual style: handcrafted clay texture, visible fingerprints, miniature sets, soft studio lighting.
- Camera: slow tabletop push-in, gentle pans, cozy close-ups.
- Texture cues: matte clay skin, felt props, tiny imperfections.
- Style lock prefix:
  claymation style, handcrafted clay texture, stop-motion miniature set,
- Default negative prompt:
  photorealistic, live action, smooth CGI, flat cartoon, text, subtitles, watermark, logo, low resolution, frame border
```

Use the same format for the other 10 files:

```markdown
STYLE: 3D animated feature film.
- Mood: bright, expressive, family-friendly.
- Visual style: stylized 3D animation, rounded shapes, warm cinematic lighting.
- Camera: smooth dolly, gentle orbit, clear character framing.
- Style lock prefix:
  stylized 3D animated film, rounded characters, warm cinematic lighting,
- Default negative prompt:
  photorealistic, live action, clay texture, pixel art, text, subtitles, watermark, logo, low resolution, frame border
```

```markdown
STYLE: Lo-fi 3D collectible figure.
- Mood: calm, cute, toy-like, cozy.
- Visual style: low-poly soft 3D figure, pastel materials, simple miniature environment.
- Camera: static product-like framing, slow push-in, gentle turntable.
- Style lock prefix:
  lo-fi 3D toy figure, pastel low-poly miniature,
- Default negative prompt:
  photorealistic, live action, complex background, harsh shadows, text, subtitles, watermark, logo, low resolution, frame border
```

```markdown
STYLE: Stickman notebook sketch.
- Mood: witty, simple, hand-drawn.
- Visual style: pencil stickman drawings on notebook paper, clean doodle animation.
- Camera: flat lay notebook view, slight hand-held paper motion.
- Style lock prefix:
  pencil stickman notebook sketch, hand-drawn doodle animation,
- Default negative prompt:
  photorealistic, 3D render, glossy surfaces, complex anatomy, text blocks, subtitles, watermark, logo, low resolution, frame border
```

```markdown
STYLE: ASMR cinematic close-up.
- Mood: soothing, intimate, sensory.
- Visual style: macro close-ups, detailed materials, slow precise motion, soft highlights.
- Camera: extreme close-up, shallow depth of field, slow glide.
- Style lock prefix:
  ASMR cinematic macro close-up, tactile materials, slow precise motion,
- Default negative prompt:
  fast cuts, wide chaotic scenes, harsh noise, text, subtitles, watermark, logo, low resolution, blurry, frame border
```

```markdown
STYLE: Neo closure vlog.
- Mood: nostalgic, quiet, personal.
- Visual style: natural light, soft film grain, vintage photo color, casual vlog realism.
- Camera: handheld but stable, gentle walking shot, diary-like framing.
- Style lock prefix:
  neo closure vlog, natural light, soft film grain,
- Default negative prompt:
  glossy commercial look, cyberpunk neon, heavy CGI, text, subtitles, watermark, logo, low resolution, frame border
```

```markdown
STYLE: Retro 8-bit pixel art.
- Mood: playful, nostalgic, arcade-like.
- Visual style: pixel art sprites, limited 8-bit palette, crisp blocky silhouettes.
- Camera: side-view or isometric game-like composition, simple looping motion.
- Style lock prefix:
  retro 8-bit pixel art, crisp sprite animation,
- Default negative prompt:
  photorealistic, live action, smooth 3D, anti-aliased painterly style, text, subtitles, watermark, logo, low resolution, frame border
```

```markdown
STYLE: Cyberpunk neon city.
- Mood: dramatic, futuristic, moody.
- Visual style: neon cyan and magenta glow, rainy reflections, dark urban atmosphere.
- Camera: slow tracking shot, reflective close-up, cinematic wide angle.
- Style lock prefix:
  cyberpunk neon city, rain reflections, cyan magenta glow,
- Default negative prompt:
  daylight pastoral scene, beige minimalism, flat cartoon, text, subtitles, watermark, logo, low resolution, frame border
```

```markdown
STYLE: Minimal beauty commercial.
- Mood: premium, clean, elegant.
- Visual style: white space, glossy product close-up, water droplets, soft studio highlights.
- Camera: slow product turntable, macro beauty shot, controlled push-in.
- Style lock prefix:
  minimal beauty commercial, white studio, glossy product macro,
- Default negative prompt:
  cluttered background, distorted product, cheap packaging, text, subtitles, watermark, logo, low resolution, frame border
```

```markdown
STYLE: Vlog with illustration overlay.
- Mood: friendly, creator-like, energetic.
- Visual style: real vlog footage mixed with clean 2D illustration overlays and stickers.
- Camera: selfie framing, casual handheld shot, clear subject.
- Style lock prefix:
  vlog realism with clean illustration overlays,
- Default negative prompt:
  heavy 3D CGI, dark cinematic horror, cluttered text overlays, watermark, logo, low resolution, blurry, frame border
```

```markdown
STYLE: Wabi-sabi Japan realism.
- Mood: quiet, natural, contemplative.
- Visual style: linen textures, aged wood, ceramic details, muted natural colors.
- Camera: still life framing, slow gentle pan, soft natural window light.
- Style lock prefix:
  wabi-sabi Japanese realism, linen texture, natural muted light,
- Default negative prompt:
  glossy neon, cluttered modern plastic, oversaturated colors, text, subtitles, watermark, logo, low resolution, frame border
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
python -m unittest tests.test_visual_style_consistency -v
```

Expected: PASS.

---

## 6. Task 3: 스타일 잠금 후처리 스킬 생성

**Files:**
- Create: `skills/visual_style_consistency_skill.py`
- Modify: `tests/test_visual_style_consistency.py`

- [ ] **Step 1: 실패 테스트 작성**

Append:

```python
from skills import visual_style_consistency_skill


class StyleLockApplyTests(unittest.TestCase):
    def test_apply_style_lock_updates_prompt_negative_ltx_and_deepy_fields(self):
        shots_data = {"shots": [{
            "shot_number": 1,
            "english_video_prompt": "a tiny dog walks across a kitchen",
            "negative_prompt": "blurry",
            "ltx_prompt": "a tiny dog walks across a kitchen",
            "ltx_negative_prompt": "blurry",
        }]}
        result = visual_style_consistency_skill.apply_style_lock(
            shots_data, "claymation", char_lock="Mochi, cream chihuahua"
        )
        shot = result["shots"][0]
        self.assertTrue(shot["english_video_prompt"].startswith("claymation style"))
        self.assertIn("Mochi, cream chihuahua", shot["english_video_prompt"])
        self.assertEqual(shot["ltx_prompt"], shot["english_video_prompt"])
        self.assertIn("photorealistic", shot["negative_prompt"])
        self.assertEqual(shot["ltx_negative_prompt"], shot["negative_prompt"])
        self.assertTrue(shot["style_lock_applied"])

    def test_apply_style_lock_trims_overlong_prompt_to_word_budget(self):
        long_prompt = " ".join(f"word{i}" for i in range(95))
        shots_data = {"shots": [{
            "shot_number": 1,
            "english_video_prompt": long_prompt,
            "negative_prompt": "blurry",
        }]}
        result = visual_style_consistency_skill.apply_style_lock(
            shots_data, "claymation", max_words=80
        )
        self.assertLessEqual(len(result["shots"][0]["english_video_prompt"].split()), 80)
```

- [ ] **Step 2: 실패 확인**

Run:

```powershell
python -m unittest tests.test_visual_style_consistency -v
```

Expected: FAIL because the new module does not exist.

- [ ] **Step 3: 구현**

Create `skills/visual_style_consistency_skill.py`:

```python
"""Apply deterministic visual style consistency locks to generated shot prompts."""
from __future__ import annotations

from typing import Any, Dict

from . import _common


def _prepend_unique(prefix: str, text: str) -> str:
    prefix = (prefix or "").strip().rstrip(",")
    text = (text or "").strip()
    if not prefix:
        return text
    if text.lower().startswith(prefix.lower()):
        return text
    return f"{prefix}, {text}" if text else prefix


def _limit_words(text: str, max_words: int) -> str:
    words = text.split()
    if max_words <= 0 or len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",")


def apply_style_lock(shots_data: Dict[str, Any], style_preset: str,
                     char_lock: str = "", input_mode: str = "",
                     max_words: int = 80) -> Dict[str, Any]:
    prefix = _common.style_lock_prefix_for(style_preset, input_mode)
    style_negative = _common.style_lock_negative_for(style_preset, input_mode)
    char_lock = (char_lock or "").strip()
    combined_prefix = ", ".join(p for p in (prefix, char_lock) if p)

    for shot in shots_data.get("shots", []):
        original = shot.get("english_video_prompt") or shot.get("ltx_prompt") or ""
        locked_prompt = _limit_words(_prepend_unique(combined_prefix, original), max_words)
        shot["english_video_prompt"] = locked_prompt
        shot["ltx_prompt"] = locked_prompt
        shot["base_prompt"] = shot.get("base_prompt") or original

        original_negative = shot.get("negative_prompt") or shot.get("ltx_negative_prompt") or ""
        locked_negative = _prepend_unique(style_negative, original_negative)
        shot["negative_prompt"] = locked_negative
        shot["ltx_negative_prompt"] = locked_negative
        shot["style_lock_applied"] = bool(combined_prefix or style_negative)
        shot["style_lock_prefix"] = combined_prefix

    return shots_data
```

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
python -m unittest tests.test_visual_style_consistency -v
```

Expected: PASS.

---

## 7. Task 4: prompt_director 저장 흐름에 스타일 잠금 연결

**Files:**
- Modify: `skills/prompt_director_skill.py`
- Test: `tests/test_visual_style_consistency.py`

- [ ] **Step 1: 실패 테스트 작성**

Add a small fake `ProjectManager` test that verifies saved `prompt_001.txt`, `negative_prompt.txt`, and exported Deepy fields are locked after `apply_style_lock()` is called. Use `tempfile.TemporaryDirectory()` and monkeypatch `llm_client.chat_json` to return one prompt.

- [ ] **Step 2: 실패 확인**

Run:

```powershell
python -m unittest tests.test_visual_style_consistency -v
```

Expected: FAIL because `generate_prompts()` does not call the new skill.

- [ ] **Step 3: 구현**

In `skills/prompt_director_skill.py`:

```python
from . import visual_style_consistency_skill
```

After the loop that fills `base_prompt`, `ltx_prompt`, score, and `deepy_prompt_pack`, but before saving `prompt_XXX.txt` files, restructure so the function:

1. Fills all shots with raw `eng`, `negative`, `base_prompt`, and initial `ltx_prompt`.
2. Calls:

```python
char_lock = str(project.get("char_lock_prompt", "")).strip()
visual_style_consistency_skill.apply_style_lock(
    shots_data,
    project.get("style_preset", ""),
    char_lock=char_lock,
    input_mode=project.get("input_mode", ""),
)
```

3. Re-runs prompt quality score and Deepy pack from the locked prompt.
4. Saves `prompt_XXX.txt`, `negative_prompt.txt`, calls `export_wangp_files(pm, shots_data, char_lock)`, then saves `shots.json`.

- [ ] **Step 4: 테스트 통과 확인**

Run:

```powershell
python -m unittest tests.test_visual_style_consistency -v
```

Expected: PASS.

---

## 8. Task 5: project.json과 shots schema 확장

**Files:**
- Modify: `core/project_manager.py`
- Modify: `core/validate_json.py`
- Test: `tests/test_visual_style_consistency.py`

- [ ] **Step 1: 실패 테스트 작성**

Append tests that call `project_manager.create_project(..., char_lock_prompt="Mochi")` and assert `project.json` contains:

```json
{
  "input_mode": "mochi",
  "style_preset": "claymation",
  "visual_style_preset": "claymation",
  "char_lock_prompt": "Mochi",
  "style_reference_image": ""
}
```

Also assert `validate_json.validate_shots({"shots":[{}]})["shots"][0]` contains `style_lock_applied`, `style_lock_prefix`, `visual_style_preset`.

- [ ] **Step 2: 실패 확인**

Run:

```powershell
python -m unittest tests.test_visual_style_consistency -v
```

Expected: FAIL because `create_project()` does not accept `char_lock_prompt`.

- [ ] **Step 3: 구현**

Change signature:

```python
def create_project(root: str, title: str, *, input_mode: str, style_preset: str,
                   target_duration: int, cfg: Dict[str, Any],
                   visual_style_preset: str = "", char_lock_prompt: str = "",
                   style_reference_image: str = "") -> ProjectManager:
```

Add to `project`:

```python
        "visual_style_preset": visual_style_preset or style_preset,
        "char_lock_prompt": char_lock_prompt,
        "style_reference_image": style_reference_image,
```

Add defaults in `validate_json.validate_shots()`:

```python
        shot.setdefault("style_lock_applied", False)
        shot.setdefault("style_lock_prefix", "")
        shot.setdefault("visual_style_preset", "")
```

- [ ] **Step 4: CLI compatibility check**

Existing CLI calls must still work because new parameters have defaults.

Run:

```powershell
python app_cli.py --help
python -m unittest tests.test_visual_style_consistency -v
```

Expected: both PASS.

---

## 9. Task 6: 구버전 프로젝트 호환 보강

**Files:**
- Modify: `app_gradio.py`
- Modify: `core/validate_json.py`
- Test: `tests/test_visual_style_consistency.py`

- [ ] **Step 1: 실패 테스트 작성**

Append a test that builds a legacy `project` dict with only:

```python
project = {"input_mode": "emotional", "style_preset": "emotional"}
```

and a legacy shot with no style fields, then verifies a helper returns:

```python
{
    "visual_style_preset": "emotional",
    "char_lock_prompt": "",
    "style_reference_image": ""
}
```

and `validate_shots()` inserts `style_lock_applied=False`.

- [ ] **Step 2: 프로젝트 정규화 helper 추가**

In `app_gradio.py`, add a small helper near project loading helpers:

```python
def _normalize_project_schema(project):
    mode = project.get("input_mode", "emotional") or "emotional"
    style = project.get("style_preset", mode) or mode
    project.setdefault("input_mode", mode)
    project.setdefault("style_preset", style)
    project.setdefault("visual_style_preset", style)
    project.setdefault("char_lock_prompt", project.get("character_lock_prompt", ""))
    project.setdefault("style_reference_image", "")
    return project
```

Call it immediately after every `pm.load_json("project.json")` in UI callbacks that use style data, especially `analyze`, `resume_project`, `refresh_lab_ui`, and prompt lab callbacks.

- [ ] **Step 3: 알 수 없는 스타일 키 fallback**

Add helper:

```python
def _effective_style(input_mode, visual_style):
    candidate = visual_style or input_mode
    if candidate not in _common.STYLE_FILES:
        return input_mode
    return candidate
```

If this helper lives in `app_gradio.py`, import `skills._common`. If it is reused by CLI, put it in `_common.py` as `effective_style_key(input_mode, visual_style)`.

- [ ] **Step 4: 호환 테스트 통과 확인**

Run:

```powershell
python -m unittest tests.test_visual_style_consistency -v
```

Expected: PASS.

---

## 10. Task 7: Gradio 만들기 탭 2-레이어 UI

**Files:**
- Modify: `app_gradio.py`

- [ ] **Step 1: constants 추가**

Below `MODE_MAP`, add:

```python
VISUAL_STYLE_AUTO = "콘텐츠 목적 자동"
VISUAL_STYLE_MAP = {
    VISUAL_STYLE_AUTO: "",
    "3D 애니 필름": "anime_3d",
    "클레이 애니메이션": "claymation",
    "로파이 3D 피규어": "lofi_3d_figure",
    "스틱맨 노트북 낙서": "stickman_sketch",
    "ASMR 시네마틱": "asmr_cinematic",
    "네오 클로저 브이로그": "neo_closure_vlog",
    "레트로 8비트": "retro_8bit",
    "사이버펑크 네온": "cyberpunk_neon",
    "미니멀 뷰티 CF": "minimal_beauty_cf",
    "브이로그 일러스트 셀프": "vlog_illus_self",
    "와비사비 재팬 리얼": "wabi_sabi_japan",
}
VISUAL_STYLE_PREVIEW = {
    VISUAL_STYLE_AUTO: "콘텐츠 목적에 맞는 기존 스타일을 그대로 사용합니다.",
    "클레이 애니메이션": "수공예 클레이 질감과 스톱모션 느낌을 모든 컷에 고정합니다.",
}
```

Fill `VISUAL_STYLE_PREVIEW` for all 11 visible labels with one Korean sentence each.

- [ ] **Step 2: `analyze()` signature 변경**

Change:

```python
def analyze(title, script, mode_label, dur_label, dur_custom):
```

to:

```python
def analyze(title, script, mode_label, visual_style_label, dur_label, dur_custom, char_lock):
```

Replace project creation style logic:

```python
    mode = MODE_MAP.get(mode_label, "emotional")
    visual_style = VISUAL_STYLE_MAP.get(visual_style_label, "")
    effective_style = visual_style or mode
```

Call:

```python
    pm = project_manager.create_project(
        cfg["project_root"], title,
        input_mode=mode, style_preset=effective_style,
        visual_style_preset=effective_style,
        char_lock_prompt=(char_lock or "").strip(),
        target_duration=duration, cfg=cfg,
    )
```

- [ ] **Step 3: UI controls 변경**

Change `mode_in` label to `콘텐츠 목적`.

Add below it:

```python
with gr.Accordion("비주얼 스타일 프리셋", open=False):
    visual_style_in = gr.Radio(
        list(VISUAL_STYLE_MAP.keys()),
        value=VISUAL_STYLE_AUTO,
        label="비주얼 스타일",
    )
    style_preview_md = gr.Markdown(VISUAL_STYLE_PREVIEW[VISUAL_STYLE_AUTO])

    def _style_preview(label):
        return VISUAL_STYLE_PREVIEW.get(label, "선택한 스타일을 모든 컷의 프롬프트에 고정합니다.")

    visual_style_in.change(_style_preview, visual_style_in, style_preview_md)

with gr.Accordion("스타일 잠금 프롬프트", open=False):
    char_lock_in = gr.Textbox(
        label="캐릭터/브랜드 잠금",
        placeholder="예: Mochi, cream-colored long-haired Chihuahua, round eyes",
        lines=2,
    )
```

- [ ] **Step 4: `make_btn.click` inputs 동기화**

Change:

```python
inputs=[title_in, script_in, mode_in, dur_in, dur_custom],
```

to:

```python
inputs=[title_in, script_in, mode_in, visual_style_in, dur_in, dur_custom, char_lock_in],
```

- [ ] **Step 5: Gradio build 검증**

Run:

```powershell
python -c "import app_gradio; app_gradio.build_ui(); print('build ok')"
```

Expected: `build ok`.

---

## 11. Task 8: LTX 연구소 character lock 연결

**Files:**
- Modify: `app_gradio.py`
- Modify: `skills/ltx_prompt_enhancer_skill.py`

- [ ] **Step 1: 현재 연구소 호출부 확인**

Search:

```powershell
rg -n "enhance_prompt|character_lock_prompt|lab" app_gradio.py skills/ltx_prompt_enhancer_skill.py
```

- [ ] **Step 2: project.json에서 char lock 전달**

Where `ltx_prompt_enhancer_skill.enhance_prompt()` is called, load:

```python
project = _load_project(project_id)
char_lock = str(project.get("char_lock_prompt", "")).strip()
```

Pass:

```python
character_lock_prompt=char_lock
```

- [ ] **Step 3: LTX 결과에도 style lock 재적용**

After a lab-enhanced `ltx_prompt` is saved into one shot, call the same style lock helper for that single shot or a `{ "shots": [shot] }` wrapper so manually enhanced prompts keep the prefix.

- [ ] **Step 4: 직접 콜백 검증**

Use a tiny project with `style_preset="claymation"` and `char_lock_prompt="Mochi"` and verify the enhanced prompt contains both when fallback path is forced by temporarily stopping Ollama or monkeypatching in a unit test.

---

## 12. Task 9: Optional CLI style validation

**Files:**
- Modify: `app_cli.py`

- [ ] **Step 1: `MODE_CHOICES`와 별개로 style choices 추가**

```python
STYLE_CHOICES = sorted(_common.STYLE_FILES.keys())
```

Import `_common` from `skills`.

- [ ] **Step 2: `--style` 도움말 개선**

Change `m.add_argument("--style", ...)` to include:

```python
choices=STYLE_CHOICES,
help="비주얼 스타일 프리셋 직접 지정. 생략하면 --mode와 동일"
```

- [ ] **Step 3: CLI help 검증**

Run:

```powershell
python app_cli.py make --help
```

Expected: new visual style keys are visible.

---

## 13. End-to-end 검증

- [ ] **Unit tests**

```powershell
python -m unittest discover -s tests -v
```

Expected: PASS.

- [ ] **CLI smoke**

```powershell
python app_cli.py check
python app_cli.py make --title "style smoke" --mode emotional --style claymation --duration 15 --script-file sample_script.txt
```

Expected:
- project created under `projects/`
- `project.json.style_preset == "claymation"`
- `prompt_001.txt` starts with `claymation style`
- `wangp_deepy_pack_001.json.wangp_copy_positive` starts with the same prefix
- Unknown style input falls back to `input_mode` and records a readable warning instead of crashing.

- [ ] **Gradio build smoke**

```powershell
python -c "import app_gradio; app_gradio.build_ui(); print('build ok')"
```

Expected: `build ok`.

- [ ] **UI callback smoke without browser**

Run a short script that imports `app_gradio.analyze`, advances the generator with:

```python
gen = app_gradio.analyze(
    "style ui smoke",
    "작은 강아지가 비 오는 창밖을 바라본다.",
    "감성 쇼츠",
    "클레이 애니메이션",
    "15초",
    15,
    "Mochi, cream Chihuahua",
)
for item in gen:
    last = item
print(last)
```

Expected: final status says 컷 준비 완료 and generated `prompt_001.txt` contains both `claymation style` and `Mochi`.

---

## 14. Future reference image guardrails

This plan intentionally does not implement reference image upload. When it is added later, use this minimum contract:

- Only `.jpg`, `.jpeg`, `.png`, and `.webp` are accepted.
- Reject files larger than 10 MB before copying.
- Copy into the project folder as `style_reference.<ext>` through `ProjectManager.path()`.
- Never store an arbitrary external absolute path in `project.json`.
- If validation fails, return a user-facing error and leave no partial file behind.
- Add tests for invalid extension, oversize file, path traversal, and successful project-local save.

---

## 15. Known risks and guardrails

- `prompt_director_skill.py` currently saves `prompt_XXX.txt` inside the same loop where prompts are first generated. Move saving after style lock so text files, `shots.json`, and Deepy packs never diverge.
- Gradio input count must match `analyze()` exactly. Any mismatch fails only at interaction time, so always run `build_ui()` and direct callback smoke.
- Prefix length can push prompts over the existing LTX prompt template’s 80-word preference. Keep every style prefix short.
- Do not implement reference image upload in this pass. It needs project-folder copy policy and Gradio allowed path handling.
- Keep new files UTF-8. Windows PowerShell 5.1 can corrupt piped Korean input, so smoke tests should use `--script-file` or Python function calls.
- Existing project files can lack every new style field. Any load path must use `_normalize_project_schema()` and `validate_shots()` defaults before touching those fields.

---

## 16. Execution options

Plan complete. Recommended execution path:

1. **Subagent-Driven:** one worker for prompt/style files, one worker for core style lock/tests, one worker for Gradio UI wiring, then integrate and run smoke tests.
2. **Inline Execution:** execute Tasks 1 through 9 in this session with checkpoints after Task 4, Task 6, and Task 7.
