"""Writes each trail's one-line blurb and the cover hook using Claude,
grounded strictly in the real stats/description fetched by the app's
data source -- replaces the judgment call a human (or an agent) makes
by hand, for use in the fully automated web tool.

Brand voice (app display name, writing rules, headline style menu) comes
from an app config (e.g. apps/ridepal.py) rather than being hardcoded
here, so this module works for any app that plugs in its own config.

Requires ANTHROPIC_API_KEY.
"""
import json
import os
import random

import anthropic

from errors import ConfigError

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT_TEMPLATE = """You write marketing copy for {display_name}, a {activity} app, for an Instagram carousel format that has already been validated and approved.

Writing rules (non-negotiable):
{brand_voice_rules}
- Ground every claim ONLY in the facts given to you (trail name, distance, difficulty, surface, and description if provided). Never invent a fact, a feature, or a number that wasn't given to you. If the description is generic or missing, write a short factual line using only the confirmed stats -- do not speculate about what the trail is like.
- Match the headline's tone to the real difficulty given. Only call trails "deadliest", "gnarliest", "not for beginners", or similar if the difficulty is Black Diamond or Double Black Diamond. Use warmer, more inviting language for Green Circle/Blue Square or "beginner-friendly"/"flow" angles. Only claim a specific feature (biggest jumps, steepest drops, etc.) if a trail's given description actually mentions it -- otherwise ground the headline in difficulty, distance, or region instead.

You will be given a JSON object with the region (a city, plus its state/province and country for broader framing), the angle (e.g. "hardest", "flow", "beginner-friendly"), a list of real trails with their real stats, and a headline_style describing the structure to use for this specific cover_headline.

cover_headline is the hook slide's headline. Write it in the structure described by headline_style, adapted naturally using the real region/trails/angle given -- headline_style is a structural direction, not a literal template, so don't force an awkward fit or leave placeholder-looking text. Pick whichever geographic level (city, state, or country) makes the sharpest hook for that structure, not always the most specific one.

Return ONLY a JSON object with this exact shape, no other text:

{{
  "cover_headline": string,
  "cover_subhead": "one short punchy line that creates curiosity or stakes, ties to the angle, under 60 characters",
  "trail_blurbs": {{"<trail_name>": "one sentence, grounded only in that trail's given facts", ...}}
}}
"""


def _client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ConfigError("ANTHROPIC_API_KEY is not set.")
    return anthropic.Anthropic(api_key=key, timeout=30.0)


def write_copy(region_name, angle_label, trails, app_config, region_state=None, region_country=None):
    """trails: list of dicts with trail_name, distance, difficulty_label,
    surface, description (from the app's data source).
    app_config: a module like apps/ridepal.py, supplying DISPLAY_NAME,
    ACTIVITY, BRAND_VOICE_RULES, and HEADLINE_STYLES.
    Returns {"cover_headline", "cover_subhead", "trail_blurbs": {name: blurb}}.
    """
    client = _client()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        display_name=app_config.DISPLAY_NAME,
        activity=app_config.ACTIVITY,
        brand_voice_rules=app_config.BRAND_VOICE_RULES,
    )
    payload = {
        "region": region_name,
        "region_state": region_state,
        "region_country": region_country,
        "angle": angle_label,
        "trail_count": len(trails),
        "headline_style": random.choice(app_config.HEADLINE_STYLES),
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
        system=system_prompt,
        messages=[{"role": "user", "content": json.dumps(payload)}],
    )
    # The model can emit a thinking block ahead of the text block, so the
    # text isn't reliably content[0] -- find the actual text block.
    text_block = next(b for b in message.content if b.type == "text")
    text = text_block.text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)
