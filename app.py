"""RidePal Daily Slideshow -- internal tool web UI.

A small local Flask app: one page with a Generate button that runs the
full pipeline (region/trail selection, real stats, real GPS geometry,
real regional photo, AI-written on-brand copy, then the approved render
template) and shows the result.
"""
import sys
import traceback
import uuid
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, send_from_directory
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "pipeline"))

import blurb_writer
import concept
import osm_geometry
import photo_unsplash
import render as render_module

OUTPUT_DIR = ROOT / "output" / "web"
DAILY_PHOTOS = ROOT / "assets" / "daily-photos"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DAILY_PHOTOS.mkdir(parents=True, exist_ok=True)

# Separate from templates/ (the Jinja slide-rendering templates used by
# render.py) to avoid any collision -- this is the web UI's own folder.
app = Flask(__name__, template_folder=str(ROOT / "web" / "templates"),
            static_folder=str(ROOT / "web" / "static"))

COUNTRY_NAMES = {"us": "United States", "canada": "Canada"}


def _region_display_and_fallbacks(region_path):
    """'/trails/canada/british-columbia/district-of-north-vancouver' ->
    ('District Of North Vancouver', ['British Columbia', 'Canada'])"""
    parts = region_path.strip("/").split("/")
    _, country_slug, state_slug, city_slug = parts[0], parts[1], parts[2], parts[3]
    city = city_slug.replace("-", " ").title()
    state = state_slug.replace("-", " ").title()
    country = COUNTRY_NAMES.get(country_slug, country_slug.replace("-", " ").title())
    return city, [state, country]


def _pick_single_trail(region):
    """Fallback when no difficulty tier has enough trails for a ranked
    list: pick one real trail, preferring one with a substantive
    description to write a better blurb from.
    """
    import random
    import trail_data as td

    paths = list(region["trail_paths"])
    random.shuffle(paths)
    best = None
    for path in paths[:15]:
        try:
            t = td.fetch_trail(path)
        except Exception:
            continue
        if not t or not t.get("difficulty_label"):
            continue
        if best is None:
            best = t
        if t.get("description") and len(t["description"]) > 120:
            return t
    return best


def run_pipeline():
    c = concept.choose_concept()
    region_display, fallback_queries = _region_display_and_fallbacks(c["region_path"])

    if c["format"] == "ranked_list":
        trails = concept.select_trails(c["region"], c["difficulty_key"], count=3, max_checks=25)
        if len(trails) < 2:
            raise RuntimeError(
                f"Only found {len(trails)} usable trail(s) in {region_display} for this "
                "angle after checking -- try generating again."
            )
        angle_label = c["difficulty_label"]
        hook_word = c["hook_word"]
    else:
        trail = _pick_single_trail(c["region"])
        if not trail:
            raise RuntimeError(f"Couldn't find a usable trail in {region_display} -- try again.")
        trails = [trail]
        angle_label = trail["difficulty_label"]
        hook_word = "a standout"

    # Real GPS geometry, via a real (headless) browser -- Overpass blocks
    # plain HTTP clients but not an actual browser navigating a real page.
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto("https://www.ridepal.app/", wait_until="domcontentloaded", timeout=20000)
        for t in trails:
            try:
                t["points"] = osm_geometry.find_trail_geometry(
                    page, t["trail_name"], t["lat"], t["lon"], expected_surface=t.get("surface"))
            except Exception:
                t["points"] = None
        browser.close()

    # Real, licensed regional photo
    photo = photo_unsplash.search_photo(region_display, fallback_queries=fallback_queries)
    if not photo:
        raise RuntimeError(f"Unsplash had nothing usable for {region_display} or its fallbacks.")
    run_id = uuid.uuid4().hex[:10]
    photo_path = DAILY_PHOTOS / f"{run_id}.jpg"
    photo_unsplash.download_photo(photo, photo_path)

    # On-brand copy, grounded only in the real stats/description above
    copy = blurb_writer.write_copy(region_display, angle_label, trails)

    slides = [{
        "type": "cover",
        "photo": str(photo_path),
        "kicker": region_display.upper(),
        "headline": copy["cover_headline"],
    }]
    for t in trails[:3]:
        slides.append({
            "type": "trail_card",
            "photo": str(photo_path),
            "card_w": 520,
            "trail_name": t["trail_name"],
            "difficulty": _difficulty_key(t["difficulty_label"]),
            "distance": t.get("distance") or "—",
            "elevation": "—",
            "peak_elevation": "—",
            "est_time": t.get("est_time") or "—",
            "points": t.get("points"),
            "lat": t.get("lat"),
            "lon": t.get("lon"),
            "blurb": copy["trail_blurbs"].get(t["trail_name"], ""),
        })

    hero = trails[0]
    slides.append({
        "type": "app_full_bleed",
        "photo": str(photo_path),
        "headline": "Find trails like this on RidePal.",
        "subtext": "The app that shows you the best trails to ride no matter where you go.",
        "trail_name": hero["trail_name"],
        "difficulty": _difficulty_key(hero["difficulty_label"]),
        "bikes_ok": True,
        "distance": hero.get("distance") or "—",
        "net_elevation": "—",
        "peak_elevation": "—",
        "est_time": hero.get("est_time") or "—",
        "surface": hero.get("surface") or "—",
        "points": hero.get("points"),
        "lat": hero.get("lat"),
        "lon": hero.get("lon"),
    })

    out_dir = OUTPUT_DIR / run_id
    paths = render_module.render_carousel(slides, out_dir)

    concept.record_use(
        c["region_path"], c.get("difficulty_key"), [t["trail_name"] for t in trails])

    caption_lines = [copy["cover_headline"]]
    if copy.get("cover_subhead"):
        caption_lines.append(copy["cover_subhead"])
    caption_lines.append("")
    for t in trails:
        caption_lines.append(f"{t['trail_name']}: {t.get('distance', '?')}, {t['difficulty_label']}")
    caption_lines.append("")
    caption_lines.append("Find trails like this on RidePal.")
    caption_lines.append("")
    caption_lines.append(
        f"Photo: {photo['photographer']} / Unsplash ({photo.get('location') or region_display})")

    return {
        "run_id": run_id,
        "region": region_display,
        "angle": f"{hook_word} ({angle_label})" if c["format"] == "ranked_list" else angle_label,
        "trail_names": [t["trail_name"] for t in trails],
        "slides": [f"/output/web/{run_id}/{p.name}" for p in paths],
        "caption": "\n".join(caption_lines),
        "photo_credit": f"{photo['photographer']} (@{photo['photographer_username']}) via Unsplash",
        "geometry_found": [bool(t.get("points")) for t in trails],
    }


def _difficulty_key(label):
    return {
        "Green Circle": "green", "Blue Square": "blue",
        "Black Diamond": "black", "Double Black Diamond": "double_black",
    }.get(label, "blue")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/generate", methods=["POST"])
def api_generate():
    try:
        result = run_pipeline()
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/output/web/<path:subpath>")
def serve_output(subpath):
    return send_from_directory(OUTPUT_DIR, subpath)


if __name__ == "__main__":
    # threaded=True: without it, Flask's dev server handles one request
    # at a time, so if a generation hangs, every subsequent click queues
    # silently behind it with no error and no log line -- confirmed this
    # happened during testing.
    app.run(debug=True, port=5055, threaded=True)
