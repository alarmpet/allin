TASK: Group the analyzed segments into VIDEO SHOTS for an AI text-to-video pipeline.

Each shot is one continuous cinematic moment of about {shot_seconds} seconds
(never longer than {max_shot_seconds} seconds).

Return ONLY this JSON object:
{
  "shots": [
    {
      "shot_number": 1,
      "chapter_id": 1,
      "source_sentences": [1],
      "korean_description": "<one-line Korean description of what we SEE in this shot>",
      "keywords": ["<English visual keywords>"],
      "emotion": "<one English word>",
      "camera": "<short English camera direction, e.g. slow push-in, static, pan right>",
      "lighting": "<short English lighting description>",
      "motion": "<short English description of the main motion/action>"
    }
  ]
}

Planning rules:
- Aim for roughly {target_shots} shots so the total length is close to the target duration.
- Keep segments in their original order. A shot may cover one or more consecutive segments.
- Merge very short/related segments; split a segment only if it clearly contains two scenes.
- "source_sentences" lists the segment_id(s) this shot is built from (in order).
- Each shot must have exactly ONE clear visual action (text-to-video models handle one action best).
- Keep the same main subject consistent across shots when the story has a recurring character.
- Do NOT write the English video prompt here; that is a later step.

STYLE CONTEXT:
{style_context}

SEGMENTS:
{segments_json}
