import unittest
from unittest.mock import patch, MagicMock
import tempfile
import os
import json

from skills import _common
from skills import visual_style_consistency_skill
from skills import prompt_director_skill
from core.project_manager import ProjectManager, create_project
from core import validate_json


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

    @patch("core.llm_client.chat_json")
    def test_prompt_director_skill_applies_style_lock(self, mock_chat_json):
        # Mock LLM output
        mock_chat_json.return_value = {
            "prompts": [
                {
                    "shot_number": 1,
                    "english_video_prompt": "a cute puppy looking out a window"
                }
            ]
        }

        cfg = {
            "ollama_model": "qwen",
            "default_max_shot_seconds": 10,
            "default_fps": 24,
            "default_frames_per_shot": 240,
            "test_resolution": "512x512",
            "final_aspect_ratio": "9:16",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create project
            pm = create_project(
                tmpdir, "test_style_project",
                input_mode="emotional", style_preset="claymation",
                target_duration=15, cfg=cfg
            )
            # Add fields from Task 5/6 (defaults check)
            project = pm.load_json("project.json")
            project["char_lock_prompt"] = "Mochi, cream Chihuahua"
            project["visual_style_preset"] = "claymation"
            pm.save_json("project.json", project)

            shots_data = {
                "shots": [{
                    "shot_number": 1,
                    "korean_description": "귀여운 강아지가 창밖을 본다.",
                    "keywords": ["강아지", "창가"],
                    "emotion": "nostalgic",
                    "camera": "slow push-in",
                    "lighting": "soft natural light",
                    "motion": "gentle motion",
                }]
            }

            result = prompt_director_skill.generate_prompts(cfg, pm, project, shots_data)
            shot = result["shots"][0]

            self.assertTrue(shot["english_video_prompt"].startswith("claymation style"))
            self.assertIn("Mochi, cream Chihuahua", shot["english_video_prompt"])
            self.assertTrue(shot["style_lock_applied"])
            self.assertEqual(shot["style_lock_prefix"], "claymation style, handcrafted clay texture, stop-motion miniature set, Mochi, cream Chihuahua")

            # Check that prompt_001.txt and deepy pack contain the locked prompts
            self.assertTrue(pm.exists("prompt_001.txt"))
            prompt_content = pm.path("prompt_001.txt")
            with open(prompt_content, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertTrue(content.startswith("claymation style"))
                self.assertIn("Mochi, cream Chihuahua", content)


class StyleCompatibilityTests(unittest.TestCase):
    def test_normalize_legacy_project_fields(self):
        legacy = {"input_mode": "emotional", "style_preset": "mochi"}
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = ProjectManager(tmpdir, "legacy_proj")
            pm.ensure_dirs()
            pm.save_json("project.json", legacy)

            # Load project.json and assert fields are normalized
            project = pm.load_json("project.json")
            self.assertEqual(project["input_mode"], "emotional")
            self.assertEqual(project["style_preset"], "mochi")
            self.assertEqual(project["visual_style_preset"], "mochi")
            self.assertEqual(project["char_lock_prompt"], "")
            self.assertEqual(project["style_reference_image"], "")

    def test_legacy_shots_validation_adds_style_lock_applied_false(self):
        legacy_shots = {
            "shots": [
                {
                    "shot_number": 1,
                    "korean_description": "test"
                }
            ]
        }
        validated = validate_json.validate_shots(legacy_shots)
        shot = validated["shots"][0]
        self.assertFalse(shot["style_lock_applied"])
        self.assertEqual(shot["style_lock_prefix"], "")
        self.assertEqual(shot["visual_style_preset"], "")
