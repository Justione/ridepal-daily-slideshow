"""Sources real regional MTB action photography via Serper.dev's Google
Images API. Google's own Custom Search JSON API stopped granting access
to new projects (confirmed: enabling it, scoping it to specific sites,
fixing API key restrictions -- none of it mattered, the project itself
is refused access), so this proxies real Google Images results through
a cheap third-party service instead: still literally Google's index,
just accessed through a vendor Google itself points traffic through
rather than a free direct API. Every candidate is then verified by
Claude vision before acceptance so a rider is confirmed visible in the
pixels, not just implied by a query or a page's alt text.

Every photo returned here is UNLICENSED for posting. These are real
photos found on the open web via Google Images, not stock photos
cleared for reuse -- `cleared` is always False. Get the photographer's
permission via the source page before posting.

Requires SERPER_API_KEY (serper.dev -- 2,500 free queries, no credit
card required, then paid) and ANTHROPIC_API_KEY (for the vision check).
"""
import base64
import os
from pathlib import Path

import anthropic
import requests

from errors import ConfigError

API_URL = "https://google.serper.dev/images"
VISION_MODEL = "claude-sonnet-5"

QUERY_SUFFIX = "mountain biker riding trail"

SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

RIDER_CHECK_PROMPT = (
    "Does this photo clearly show a person riding a mountain bike "
    "(a visible rider actively on the bike, not just a bike alone or an "
    "empty trail)? Answer with exactly one word: yes or no."
)


def _api_key():
    key = os.environ.get("SERPER_API_KEY")
    if not key:
        raise ConfigError(
            "SERPER_API_KEY is not set. Sign up free at serper.dev "
            "(2,500 free queries, no credit card required) and set the "
            "key it gives you as SERPER_API_KEY."
        )
    return key


def _anthropic_client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ConfigError("ANTHROPIC_API_KEY is not set.")
    return anthropic.Anthropic(api_key=key, timeout=30.0)


def _search_candidates(query, api_key, num=10):
    resp = requests.post(
        API_URL,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "num": num},
        timeout=20,
    )
    if resp.status_code in (400, 401, 403):
        # A bad/missing key or an exhausted free tier -- a setup
        # problem, not "no photos for this region", so retrying with a
        # different region won't fix it.
        raise ConfigError(f"Serper Images API error ({resp.status_code}): {resp.text}")
    resp.raise_for_status()
    return resp.json().get("images", [])


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
    """Searches real Google Images results (region, then each fallback
    query in order), downloads candidates, and returns the first one
    Claude actually confirms has a visible rider on a bike. Returns None
    if nothing verified across every tier.
    """
    api_key = _api_key()
    client = _anthropic_client()

    queries = [region_query] + (fallback_queries or [])
    for q in queries:
        try:
            items = _search_candidates(f"{q} {QUERY_SUFFIX}", api_key)
        except ConfigError:
            raise
        except requests.RequestException:
            continue

        for item in items[:max_checked_per_tier]:
            image_url = item.get("imageUrl")
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
                "source_page": item.get("link"),
                "source_site": item.get("domain") or item.get("source"),
                "title": item.get("title"),
                "matched_query": q,
                "cleared": False,
            }

    return None


def save_photo(photo, out_path):
    out_path = Path(out_path)
    out_path.write_bytes(photo["bytes"])
    return out_path
