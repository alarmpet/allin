TASK: Write the final ENGLISH video-generation prompt for each shot below
(for an LTX2 / WanGP text-to-video model).

Return ONLY this JSON object:
{
  "prompts": [
    {
      "shot_number": 1,
      "english_video_prompt": "<the full English prompt>"
    }
  ]
}

Each english_video_prompt MUST include, woven into natural language:
- main subject (clear, concrete)
- subject consistency cue (keep the recurring character/look consistent)
- ONE clear action
- environment / setting
- camera movement (cinematic camera moves: e.g. slow pan, steady dolly back, 35mm lens)
- lighting
- mood / atmosphere
- visual style (e.g. cinematic realism, realistic textures, shallow depth of field)
- vertical short-form composition
- audio details / ambient sound (CRITICAL: since LTX-2 generates synchronized audio, include subtle audio cues like "the gentle rustling of paper", "quiet ambient wind", or "soft background chatter" matching the scene)

Rules:
- Do NOT include negative keywords like "no text", "no subtitles", "no logo", "no watermark" in this positive prompt. They will be placed in the negative prompt instead.
- Do NOT write duration hints like "about 6 seconds" in the prompt text.
- Fluent English only. One flowing prompt per shot (no bullet lists).
- Be specific and filmable. Avoid abstract/non-visual phrases.
- Reuse the shot's camera/lighting/motion/keywords from the plan.
- Keep each prompt under ~80 words.

STYLE CONTEXT:
{style_context}

SHOTS:
{shots_json}
