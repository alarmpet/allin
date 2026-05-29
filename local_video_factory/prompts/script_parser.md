TASK: Analyze the Korean script below and split it into meaningful sentence-level segments.

Return ONLY this JSON object (CRITICAL: Do NOT change this root structure or key names regardless of the visual style context below. The root MUST be {"segments": [...]}):
{
  "segments": [
    {
      "segment_id": 1,
      "sentence": "<original sentence from the script, in Korean>",
      "meaning": "<one-line Korean explanation of what this sentence conveys>",
      "emotion": "<one English word: e.g. calm, melancholy, joyful, tense, warm, neutral>",
      "keywords": ["<2-4 English visual keywords>"],
      "visual_potential": "<high | medium | low>",
      "tts_text": "<a clean, natural Korean narration line for this segment, ready to be spoken aloud>"
    }
  ]
}

Guidelines:
- Split on natural sentence boundaries. Keep the original wording in "sentence".
- "tts_text" may lightly polish the sentence for smooth narration, but keep the meaning.
- "keywords" describe what should be VISIBLE on screen (subjects, setting, objects), in English.
- If the input is a one-line idea, expand it into a few logical narration segments.
- Do NOT invent unrelated content. Stay faithful to the script.

STYLE CONTEXT:
{style_context}

TARGET TOTAL DURATION (seconds): {target_duration}

SCRIPT:
{script}
