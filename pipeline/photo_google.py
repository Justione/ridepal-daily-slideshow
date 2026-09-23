"""Sources real regional MTB action photography via Google's official
Custom Search JSON API, then verifies each candidate actually shows a
rider on a bike using Claude vision before accepting it. Stock libraries
like Unsplash turned out not to have enough real trail-riding action
shots, and a keyword filter on a photo's alt text/title isn't reliable
enough to guarantee a rider is actually in frame -- this checks the
actual pixels.

Every photo returned here is UNLICENSED for posting. These are real
photos found on the open web, not stock photos cleared for reuse --
`cleared` is always False. Get the photographer's permission via the
source page before posting, same as the original workflow.

Requires GOOGLE_API_KEY, GOOGLE_CSE_ID (a Programmable Search Engine at
programmablesearchengine.google.com, configured for image search), and
ANTHROPIC_API_KEY (for the vision check).
"""
import base64
import os
from pathlib import Path

import anthropic
import requests

from errors import ConfigError

API_BASE = "https://www.googleapis.com/customsearch/v1"
VISION_MODEL = "claude-sonnet-5"

QUERY_SUFFIX = "mountain biker riding trail"

SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

RIDER_CHECK_PROMPT = (
    "Does this photo clearly show a person riding a mountain bike "
    "(a visible rider actively on the bike, not just a bike alone or an "
    "empty trail)? Answer with exactly one word: yes or no."
)


def _keys():
    api_key = os.environ.get("GOOGLE_API_KEY")
    cse_id = os.environ.get("GOOGLE_CSE_ID")
    if not api_key or not cse_id:
        raise ConfigError(
            "GOOGLE_API_KEY and GOOGLE_CSE_ID are not set. Create a free "
            "Programmable Search Engine at programmablesearchengine.google.com "
            "(with image search turned on) for GOOGLE_CSE_ID, and an API key "
            "at console.cloud.google.com/apis/credentials with the Custom "
            "Search API enabled for GOOGLE_API_KEY."
        )
    return api_key, cse_id


def _anthropic_client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ConfigError("ANTHROPIC_API_KEY is not set.")
    return anthropic.Anthropic(api_key=key, timeout=30.0)


def _search_candidates(query, api_key, cse_id, num=10):
    resp = requests.get(API_BASE, params={
        "key": api_key,
        "cx": cse_id,
        "q": query,
        "searchType": "image",
        "num": min(num, 10),
        "safe": "active",
        "imgSize": "large",
    }, timeout=20)
    if resp.status_code in (400, 403):
        # A bad key, a disabled API, or a misconfigured search engine --
        # this is a setup problem, not "no photos for this region", and
        # retrying with a different region won't fix it.
        detail = resp.json().get("error", {}).get("message", resp.text)
        raise ConfigError(f"Google Custom Search API error ({resp.status_code}): {detail}")
    resp.raise_for_status()
    return resp.json().get("items", [])


def _download_image(url, max_bytes=15_000_000):
    resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in SUPPORTED_MEDIA_TYPES:
        return None, None
    if len(resp.content) > max_bytes:
        return None, None
    return resp.content, content_type


def _has_visible_rider(image_bytes, media_type, client):
    b64 = base64.b64encode(image_bytes).decode()
    message = client.messages.create(
        model=VISION_MODEL,
        max_tokens=10,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                {"type": "text", "text": RIDER_CHECK_PROMPT},
            ],
        }],
    )
    answer = message.content[0].text.strip().lower()
    return answer.startswith("yes")


def find_photo(region_query, fallback_queries=None, max_checked_per_tier=6):
    """Searches Google Images (region, then each fallback query in order),
    downloads candidates, and returns the first one Claude actually
    confirms has a visible rider on a bike. Returns None if nothing
    verified across every tier.
    """
    api_key, cse_id = _keys()
    client = _anthropic_client()

    queries = [region_query] + (fallback_queries or [])
    for q in queries:
        try:
            items = _search_candidates(f"{q} {QUERY_SUFFIX}", api_key, cse_id)
        except ConfigError:
            raise
        except requests.RequestException:
            continue

        for item in items[:max_checked_per_tier]:
            image_url = item.get("link")
            if not image_url:
                continue
            try:
                content, media_type = _download_image(image_url)
            except requests.RequestException:
                continue
            if not content:
                continue
            try:
                if not _has_visible_rider(content, media_type, client):
                    continue
            except Exception:
                continue

            return {
                "bytes": content,
                "content_type": media_type,
                "source_page": (item.get("image") or {}).get("contextLink") or item.get("displayLink"),
                "source_site": item.get("displayLink"),
                "title": item.get("title"),
                "matched_query": q,
                "cleared": False,
            }

    return None


def save_photo(photo, out_path):
    out_path = Path(out_path)
    out_path.write_bytes(photo["bytes"])
    return out_path
