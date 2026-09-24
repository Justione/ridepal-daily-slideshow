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

Rather than accepting the first candidate with a visible rider, every
candidate in a tier gets scored by Claude vision on both image quality
and how serious/skilled the riding action is, and the best-scoring one
wins -- a low bar ("yes, there's a bike") wasn't good enough, since nothing
here should ship as a low-effort snapshot. The same vision call also
locates the rider in the frame (focal_x/focal_y), since the render step
crops every photo into a tall portrait frame -- a wide shot with the
rider off to one side would otherwise get center-cropped down to empty
sky or ground.

Requires SERPER_API_KEY (serper.dev -- 2,500 free queries, no credit
card required, then paid) and ANTHROPIC_API_KEY (for the vision check).
"""
import base64
import os
import re
from pathlib import Path

import anthropic
import requests

from errors import ConfigError

API_URL = "https://google.serper.dev/images"
VISION_MODEL = "claude-sonnet-5"

QUERY_SUFFIX = "mountain biker riding trail"

SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Below this, a photo is rejected even if it's the best of a bad batch --
# the tier's fallback (or the app's own retry-a-different-region logic)
# is preferred over shipping a mediocre photo.
MIN_PHOTO_SCORE = 6

QUALITY_ACTION_PROMPT = (
    "Analyze this photo for use as hero marketing imagery for a mountain "
    "biking app. It will be cropped into a TALL PORTRAIT frame, so only a "
    "vertical slice of this image will actually be shown -- knowing where "
    "the rider sits in the frame matters as much as the rating.\n\n"
    "Respond with ONLY three integers separated by commas, nothing else, "
    "in this exact order:\n"
    "1. score (0 to 10): score 0 if there is no mountain biker clearly and "
    "actively visible riding a bike. Otherwise score both image quality "
    "(sharp, well exposed, well composed, looks like real action "
    "photography; blurry, dark, low-resolution, or amateur snapshots "
    "score low) and how serious/skilled the riding is (a big jump, a "
    "drop, a technical rock garden, a steep fast downhill run, or hard "
    "berms at speed score highest; casual pedaling on flat/easy ground "
    "scores low even if the photo itself is sharp).\n"
    "2. focal_x (0 to 100): the rider's horizontal position as a percent "
    "of image width from the left edge (0 = far left, 50 = center, "
    "100 = far right). Use 50 if there is no rider.\n"
    "3. focal_y (0 to 100): the rider's vertical position as a percent of "
    "image height from the top edge (0 = top, 50 = middle, 100 = bottom). "
    "Use 50 if there is no rider.\n\n"
    "Example response: 8,72,45"
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


def _evaluate_photo(image_bytes, media_type, client):
    """Returns (score, focal_x, focal_y). focal_x/focal_y locate the rider
    in the frame (0-100, percent from the left/top) so the render step can
    crop toward the actual subject instead of blindly centering -- a wide
    action shot with the rider off to one side would otherwise get
    cropped down to empty sky or ground in the portrait frame."""
    message = client.messages.create(
        model=VISION_MODEL,
        max_tokens=20,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type,
                    "data": base64.b64encode(image_bytes).decode(),
                }},
                {"type": "text", "text": QUALITY_ACTION_PROMPT},
            ],
        }],
    )
    # The model can emit a thinking block ahead of the text block, so the
    # text isn't reliably content[0] -- find the actual text block.
    text_block = next(b for b in message.content if b.type == "text")
    numbers = [int(n) for n in re.findall(r"\d+", text_block.text)]
    if len(numbers) < 3:
        return 0, 50, 50
    score, focal_x, focal_y = numbers[:3]
    return score, max(0, min(100, focal_x)), max(0, min(100, focal_y))


def find_photo(region_query, fallback_queries=None, max_checked_per_tier=8):
    """Searches real Google Images results (region, then each fallback
    query in order). Within each tier, every candidate is downloaded and
    scored by Claude vision for quality and how serious the riding action
    is, and the best-scoring candidate that clears MIN_PHOTO_SCORE wins --
    not just the first one with a rider in it. Returns None if nothing
    across every tier clears the bar.
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

        candidates = []
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
                score, focal_x, focal_y = _evaluate_photo(content, media_type, client)
            except Exception:
                continue
            if score > 0:
                candidates.append((score, focal_x, focal_y, item, content, media_type))

        if not candidates:
            continue
        candidates.sort(key=lambda c: c[0], reverse=True)
        best_score, focal_x, focal_y, best_item, best_content, best_media_type = candidates[0]
        if best_score >= MIN_PHOTO_SCORE:
            return {
                "bytes": best_content,
                "content_type": best_media_type,
                "source_page": best_item.get("link"),
                "source_site": best_item.get("domain") or best_item.get("source"),
                "title": best_item.get("title"),
                "matched_query": q,
                "cleared": False,
                "quality_score": best_score,
                "focal_x": focal_x,
                "focal_y": focal_y,
            }

    return None


def save_photo(photo, out_path):
    out_path = Path(out_path)
    out_path.write_bytes(photo["bytes"])
    return out_path
