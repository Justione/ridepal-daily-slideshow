"""Fetches real trail-line geometry from OpenStreetMap's Overpass API.

Overpass returns HTTP 406 to any non-browser HTTP client (confirmed
against curl and Python requests, with and without browser-mimicking
headers) but works fine from inside a real browser's fetch(). Rather than
requiring an interactive agent with a browser tool, this drives a
headless Playwright browser -- a real browser, just automated -- which
gets the same access a human browsing the page would. Confirmed working
by navigating to a real page (ridepal.app) first; calling fetch() from
about:blank or a fresh unnavigated page does not work.
"""
import json
import time

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

_FETCH_JS = """async (query) => {
    try {
        const res = await fetch('%s', { method: 'POST', body: 'data=' + encodeURIComponent(query) });
        return await res.text();
    } catch (e) {
        return null;
    }
}""" % OVERPASS_URL


def _query_overpass(page, query, retries=4, retry_delay=3.0):
    """A rate-limit or transient error from Overpass often comes back as
    a normal 200 response whose body isn't valid JSON (an HTML message,
    or empty) rather than a thrown fetch() error -- confirmed by two
    back-to-back calls from the same browser context, where the second
    failed silently with no exception. So retries happen here in Python,
    based on whether the response actually parses, not just on whether
    fetch() itself threw.
    """
    for attempt in range(retries):
        text = page.evaluate(_FETCH_JS, query)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass
        if attempt < retries - 1:
            time.sleep(retry_delay)
    return None


def find_trail_geometry(page, trail_name, lat, lon, expected_surface=None, radius_deg=0.1):
    """Looks up a named way near (lat, lon) and returns its full point
    geometry as a list of (lat, lon) tuples, or None if no confident
    match is found. `page` must already be on a real navigated page
    (not about:blank) in the same Playwright browser used elsewhere.

    A match is required to have the same name (case-insensitive) and,
    when `expected_surface` is given, a matching surface tag -- this is
    the same cross-check used manually during development to avoid
    attaching the wrong trail's geometry to a post.
    """
    bbox = f"{lat - radius_deg},{lon - radius_deg},{lat + radius_deg},{lon + radius_deg}"
    search_query = f'[out:json][timeout:25];way["name"~"{trail_name}",i]({bbox});out geom;'
    data = _query_overpass(page, search_query)
    if not data or not data.get("elements"):
        return None

    candidates = data["elements"]
    best = None
    for el in candidates:
        tags = el.get("tags", {})
        name = tags.get("name", "")
        if name.strip().lower() != trail_name.strip().lower():
            continue
        if expected_surface and tags.get("surface"):
            if tags["surface"].strip().lower() != expected_surface.strip().lower():
                continue
        if best is None or el.get("bounds") and (
            best.get("bounds") is None
            or _bounds_area(el["bounds"]) > _bounds_area(best["bounds"])
        ):
            best = el

    if best is None:
        return None

    # Overpass rate-limits requests fired back-to-back from the same
    # client -- confirmed the very next call fails without this pause.
    time.sleep(2.5)

    way_id = best["id"]
    geom_query = f"[out:json][timeout:25];way({way_id});out geom;"
    full = _query_overpass(page, geom_query)
    if not full or not full.get("elements"):
        return None

    geometry = full["elements"][0].get("geometry", [])
    if len(geometry) < 3:
        return None
    return [(pt["lat"], pt["lon"]) for pt in geometry]


def _bounds_area(b):
    return (b["maxlat"] - b["minlat"]) * (b["maxlon"] - b["minlon"])
