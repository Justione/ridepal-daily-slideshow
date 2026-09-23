"""Writes each trail's one-line blurb and the cover hook using Claude,
grounded strictly in the real stats/description fetched by trail_data.py
-- replaces the judgment call a human (or an agent) makes by hand, for
use in the fully automated web tool.

Requires ANTHROPIC_API_KEY.
"""
import json
import os

import anthropic

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = """You write one-line marketing blurbs for RidePal, a mountain bike trail app, for an Instagram carousel format that has already been validated and approved.

Writing rules (non-negotiable):
- No dashes of any kind (no -, no --, no em dash).
- No emojis.
- No hashtags.
- No corporate language ("revolutionary", "ultimate", "next level", "game-changer").
- Sounds like a rider talking to another rider, not a brand talking to a customer. Matter-of-fact, slightly punchy, grounded in real riding.
- Ground every claim ONLY in the facts given to you (trail name, distance, difficulty, surface, and description if provided). Never invent a fact, a feature, or a number that wasn't given to you. If the description is generic or missing, write a short factual line using only the confirmed stats -- do not speculate about what the trail is like.

You will be given a JSON object with the region, the angle (e.g. "hardest", "flow", "beginner-friendly"), and a list of real trails with their real stats. Return ONLY a JSON object with this exact shape, no other text:

{
  "cover_headline": "N of the <angle> MTB trails in <region>",
  "cover_subhead": "one short punchy line that creates curiosity or stakes, ties to the angle, under 60 characters",
  "trail_blurbs": {"<trail_name>": "one sentence, grounded only in that trail's given facts", ...}
}
"""


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    return anthropic.Anthropic(api_key=key, timeout=30.0)


def write_copy(region_name, angle_label, trails):
    """trails: list of dicts with trail_name, distance, difficulty_label,
    surface, description (from trail_data.fetch_trail).
    Returns {"cover_headline", "cover_subhead", "trail_blurbs": {name: blurb}}.
    """
    client = _client()
    payload = {
        "region": region_name,
        "angle": angle_label,
        "trail_count": len(trails),
        "trails": [
            {
                "trail_name": t["trail_name"],
                "distance": t.get("distance"),
                "difficulty_label": t.get("difficulty_label"),
                "surface": t.get("surface"),
                "description": t.get("description"),
            }
            for t in trails
        ],
    }

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
