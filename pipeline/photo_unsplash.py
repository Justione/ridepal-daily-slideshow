"""Sources real, professional-quality regional MTB action photography via
Unsplash's official API -- replaces the manual browse-and-judge process
with an automatable equivalent that still respects the same quality bar
Justin set: modern bikes, real riders, real action, not old/amateur shots.

Requires UNSPLASH_ACCESS_KEY. Get a free key at unsplash.com/developers.
"""
import os
import urllib.request
from pathlib import Path

import requests

API_BASE = "https://api.unsplash.com"

# Keywords that bias results toward action shots of a rider on a bike,
# not scenery/landscape-only photos or unrelated "biking" results.
QUERY_SUFFIX = "mountain biking"

# Words in a photo's own description/alt text that suggest it's NOT what
# we want (old/vintage framing, or clearly not an MTB action shot).
REJECT_KEYWORDS = {"vintage", "retro", "old bike", "bmx trick", "road bike", "motorcycle"}


def _api_key():
    key = os.environ.get("UNSPLASH_ACCESS_KEY")
    if not key:
        raise RuntimeError(
            "UNSPLASH_ACCESS_KEY is not set. Get a free key at "
            "unsplash.com/developers and set it as an environment variable."
        )
    return key


def search_photo(region_query, fallback_queries=None, min_likes=0):
    """Searches Unsplash for a real regional MTB action photo, trying
    `region_query` first and then each of `fallback_queries` in order
    (e.g. state, then country) -- matching the tiered fallback Justin
    asked for: exact region, then broader region, then just the country.

    Returns a dict with the photo's id, urls, photographer, and location,
    or None if nothing suitable was found in any tier.
    """
    key = _api_key()
    queries = [region_query] + (fallback_queries or [])

    for q in queries:
        resp = requests.get(
            f"{API_BASE}/search/photos",
            params={
                "query": f"{q} {QUERY_SUFFIX}",
                "orientation": "portrait",
                "per_page": 10,
                "content_filter": "high",
            },
            headers={"Authorization": f"Client-ID {key}"},
            timeout=20,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])

        candidates = [r for r in results if r.get("likes", 0) >= min_likes]
        candidates = [
            r for r in candidates
            if not any(kw in (r.get("alt_description") or "").lower() for kw in REJECT_KEYWORDS)
        ]
        # prefer whichever has the most likes, as a rough quality proxy
        candidates.sort(key=lambda r: r.get("likes", 0), reverse=True)

        if candidates:
            best = candidates[0]
            return {
                "id": best["id"],
                "download_location": best["links"]["download_location"],
                "raw_url": best["urls"]["raw"],
                "photographer": best["user"]["name"],
                "photographer_username": best["user"]["username"],
                "location": (best.get("location") or {}).get("name"),
                "matched_query": q,
            }

    return None


def download_photo(photo, out_path, width=1600):
    """Downloads the photo and triggers Unsplash's required download-
    tracking event (per their API guidelines: every use of a photo must
    ping the download_location endpoint, separate from the image fetch
    itself)."""
    key = _api_key()
    requests.get(
        photo["download_location"],
        headers={"Authorization": f"Client-ID {key}"},
        timeout=15,
    )

    url = f"{photo['raw_url']}&w={width}&fm=jpg&q=85&fit=max"
    out_path = Path(out_path)
    urllib.request.urlretrieve(url, out_path)
    return out_path
