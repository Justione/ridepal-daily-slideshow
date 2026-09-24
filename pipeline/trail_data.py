"""Fetches real trail and region data straight from ridepal.app's own
server-rendered pages -- no scraping heuristics, no guessing. Every trail
page embeds a schema.org SportsActivityLocation JSON-LD block with clean
structured fields (name, region, difficulty, distance, time, surface,
technical rating, geo coordinates), which is what this reads.

Plain `requests` works fine for ridepal.app (confirmed: server-rendered,
no JS needed). It does NOT work for the OpenStreetMap Overpass API used
for real trail-line geometry (overpass-api.de returns 406 to any
non-browser client, confirmed against both curl and requests with a
browser User-Agent) -- that lookup has to go through the agent's own
browser tool during the daily run, not through this module.
"""
import json
import re

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36"
    )
}

BASE = "https://www.ridepal.app"


def _ld_json_blocks(html):
    return re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)


def fetch_trail(path_or_url):
    """path_or_url like '/trails/us/utah/ogden/porcupine' or a full URL.
    Returns a dict with the trail's real, verified stats -- or None if the
    page has no SportsActivityLocation block (doesn't exist / bad slug).
    """
    url = path_or_url if path_or_url.startswith("http") else BASE + path_or_url
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    trail = None
    for block in _ld_json_blocks(resp.text):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        graph = data.get("@graph", [data])
        for node in graph:
            if node.get("@type") == "SportsActivityLocation":
                trail = node
                break
        if trail:
            break
    if not trail:
        return None

    props = {p["name"]: p["value"] for p in trail.get("additionalProperty", [])}
    geo = trail.get("geo", {})
    addr = trail.get("address", {})

    return {
        "trail_name": trail.get("name"),
        "url": trail.get("url", url),
        "region": trail.get("containedInPlace", {}).get("name")
                  or f"{addr.get('addressLocality', '')}, {addr.get('addressRegion', '')}".strip(", "),
        "distance": props.get("Distance"),
        "difficulty_label": props.get("Difficulty"),
        "est_time": props.get("Estimated ride time"),
        "surface": props.get("Surface"),
        "technical_rating": props.get("Technical Rating"),
        "direction": props.get("Direction"),
        "lat": geo.get("latitude"),
        "lon": geo.get("longitude"),
        "description": trail.get("description"),
    }


_ELEVATION_STAT_JS = """(label) => {
    const els = Array.from(document.querySelectorAll('*'))
        .filter(e => e.children.length === 0 && e.textContent.trim().toLowerCase() === label);
    for (const e of els) {
        const val = e.previousElementSibling ? e.previousElementSibling.textContent
                   : (e.nextElementSibling ? e.nextElementSibling.textContent : null);
        if (val) {
            const v = val.trim();
            if (v && v !== '...' && v !== '—' && v !== '-') return v;
        }
    }
    return null;
}"""


def fetch_elevation(page, trail_url, timeout_ms=10000):
    """Net and peak elevation are NOT in the trail page's server-rendered
    HTML or its JSON-LD block -- confirmed by checking the raw response
    directly: the labels are static but the actual numbers are injected
    client-side after the page loads, taking up to several seconds (a
    fresh page shows "..." then a placeholder dash before the real value
    appears). So this needs a real browser: it navigates to the trail's
    own page and waits for the site's own elevation values to actually
    resolve, rather than reading whatever's there immediately.

    `page` must be a live Playwright page in the same browser used for
    OSM geometry lookups elsewhere in the pipeline -- navigating it here
    is fine, Overpass only needs the page to be on some real origin.

    Returns (net_elevation, peak_elevation) as strings, or None for
    whichever never resolved within timeout_ms (never fabricated).
    """
    page.goto(trail_url, wait_until="domcontentloaded", timeout=20000)

    def wait_for(label):
        try:
            handle = page.wait_for_function(_ELEVATION_STAT_JS, arg=label, timeout=timeout_ms)
            return handle.json_value()
        except Exception:
            return None

    net_elevation = wait_for("net elevation")
    peak_elevation = wait_for("peak elevation")
    return net_elevation, peak_elevation


DIFFICULTY_LABEL_TO_KEY = {
    "Green Circle": "green",
    "Blue Square": "blue",
    "Black Diamond": "black",
    "Double Black Diamond": "double_black",
    "Double Black": "double_black",
}


def fetch_region(region_path_or_url):
    """region_path_or_url like '/trails/canada/british-columbia/district-of-north-vancouver'.
    Returns the region's real difficulty mix (trail counts per tier) and
    trail list, scraped from ridepal.app's own region index page -- this
    is what lets concept.py check a region actually HAS enough real trails
    for whatever angle it's considering, instead of assuming and getting
    burned like the Moab mistake.
    """
    url = region_path_or_url if region_path_or_url.startswith("http") else BASE + region_path_or_url
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    html = resp.text

    total_match = re.search(r"Explore ([\d,]+)\s+(?:mapped mountain bike (?:routes|trails)|MTB Trails)", html)
    total_trails = int(total_match.group(1).replace(",", "")) if total_match else None

    difficulty_mix = {}
    for label, key in DIFFICULTY_LABEL_TO_KEY.items():
        m = re.search(
            re.escape(label) + r'</span></div><span class="[^"]*">(\d+)</span>', html)
        if m:
            difficulty_mix[key] = difficulty_mix.get(key, 0) + int(m.group(1))

    trail_links = sorted(set(re.findall(
        r'href="(/trails/[a-z0-9\-]+/[a-z0-9\-]+/[a-z0-9\-]+/[a-z0-9\-]+)"', html)))

    return {
        "url": url,
        "total_trails": total_trails,
        "difficulty_mix": difficulty_mix,
        "trail_paths": trail_links,
    }
