"""RidePal Daily Slideshow -- internal tool web UI.

A small local Flask app: one page with a Generate button that runs the
full pipeline (region/trail selection, real stats, real GPS geometry,
a real photo with a verified rider in it, AI-written on-brand copy, then
the approved render template) and shows the result. Every run is also
saved to state/history/ so past slideshows stay browsable instead of
being lost the moment a new one is generated.
"""
import json
import sys
import traceback
import uuid
from datetime import datetime, timezone
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
import photo_serper
import render as render_module
import trail_data
from errors import ConfigError

OUTPUT_DIR = ROOT / "output" / "web"
DAILY_PHOTOS = ROOT / "assets" / "daily-photos"
HISTORY_DIR = ROOT / "state" / "history"
HISTORY_INDEX = ROOT / "state" / "history_index.json"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
DAILY_PHOTOS.mkdir(parents=True, exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

# Separate from templates/ (the Jinja slide-rendering templates used by
# render.py) to avoid any collision -- this is the web UI's own folder.
app = Flask(__name__, template_folder=str(ROOT / "web" / "templates"),
            static_folder=str(ROOT / "web" / "static"))

COUNTRY_NAMES = {"us": "United States", "canada": "Canada"}

# A region that fails for a data-availability reason (not enough real
# trails, no verified rider photo) is worth retrying elsewhere. A
# ConfigError (missing API key) is not -- retrying just repeats the same
# failure, so it's raised immediately instead of burning through retries.
MAX_ATTEMPTS = 3

CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg", "image/png": ".png",
    "image/gif": ".gif", "image/webp": ".webp",
}


def _region_display_and_fallbacks(region_path):
    """'/trails/canada/british-columbia/district-of-north-vancouver' ->
    ('District Of North Vancouver', ['British Columbia', 'Canada'])"""
    parts = region_path.strip("/").split("/")
    _, country_slug, state_slug, city_slug = parts[0], parts[1], parts[2], parts[3]
    city = city_slug.replace("-", " ").title()
    state = state_slug.replace("-", " ").title()
    country = COUNTRY_NAMES.get(country_slug, country_slug.replace("-", " ").title())
    return city, [state, country]


DIFFICULTY_RANK = {
    "Double Black Diamond": 3, "Black Diamond": 2, "Blue Square": 1, "Green Circle": 0,
}


def _pick_single_trail(region):
    """Fallback when no difficulty tier has enough trails for a ranked
    list: pick one real trail, preferring the hardest one available (the
    feed should lean into whatever real extreme terrain exists rather
    than defaulting to whatever's easiest, same reasoning as pick_angle)
    and, among similarly hard trails, one with a substantive description
    to write a better blurb from.
    """
    import random

    paths = list(region["trail_paths"])
    random.shuffle(paths)
    checked = []
    for path in paths[:15]:
        try:
            t = trail_data.fetch_trail(path)
        except Exception:
            continue
        if not t or not t.get("difficulty_label"):
            continue
        checked.append(t)

    if not checked:
        return None
    checked.sort(key=lambda t: (
        DIFFICULTY_RANK.get(t["difficulty_label"], 0),
        1 if t.get("description") and len(t["description"]) > 120 else 0,
    ), reverse=True)
    return checked[0]


def _attempt_pipeline(avoid_regions):
    """One full attempt at a concept + render. Raises RuntimeError on
    failure. If the failure is specific to the region's own data (not a
    config problem), the exception carries a `.region_path` attribute so
    the caller can avoid that region on the next attempt.
    """
    c = concept.choose_concept(avoid_regions=avoid_regions)
    region_path = c["region_path"]
    region_display, fallback_queries = _region_display_and_fallbacks(region_path)

    try:
        if c["format"] == "ranked_list":
            trails = concept.select_trails(c["region"], c["difficulty_key"], count=3, max_checks=25)
            if len(trails) < 2:
                raise RuntimeError(
                    f"Only found {len(trails)} usable trail(s) in {region_display} for this angle.")
            angle_label = c["difficulty_label"]
            hook_word = c["hook_word"]
        else:
            trail = _pick_single_trail(c["region"])
            if not trail:
                raise RuntimeError(f"Couldn't find a usable trail in {region_display}.")
            trails = [trail]
            angle_label = trail["difficulty_label"]
            hook_word = "a standout"

        # Real GPS geometry, via a real (headless) browser -- Overpass
        # blocks plain HTTP clients but not an actual browser navigating
        # a real page. Net/peak elevation also need a real browser: the
        # numbers are injected client-side after the trail page loads
        # (confirmed: the raw HTML never has them, and a fresh page shows
        # a loading placeholder for several seconds before the real
        # value appears), so this waits for them rather than reading
        # whatever's there immediately.
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto("https://www.ridepal.app/", wait_until="domcontentloaded", timeout=20000)
            for t in trails:
                try:
                    t["net_elevation"], t["peak_elevation"] = trail_data.fetch_elevation(page, t["url"])
                except Exception:
                    t["net_elevation"], t["peak_elevation"] = None, None
                try:
                    t["points"] = osm_geometry.find_trail_geometry(
                        page, t["trail_name"], t["lat"], t["lon"], expected_surface=t.get("surface"))
                except Exception:
                    t["points"] = None
            browser.close()

        # A real photo from Google Images with a Claude-vision-verified
        # rider actually in frame. This is NOT a licensed stock photo --
        # get the photographer's permission via the source page before
        # posting.
        photo = photo_serper.find_photo(region_display, fallback_queries=fallback_queries)
        if not photo:
            raise RuntimeError(
                f"No photo with a verified rider found for {region_display} or its fallbacks.")
        run_id = uuid.uuid4().hex[:10]
        ext = CONTENT_TYPE_EXT.get(photo["content_type"], ".jpg")
        photo_path = DAILY_PHOTOS / f"{run_id}{ext}"
        photo_serper.save_photo(photo, photo_path)
        # Crop toward the rider's actual position, not the image's
        # geometric center -- a wide shot with an off-center rider was
        # getting center-cropped down to empty sky/ground otherwise.
        photo_object_position = f"{photo.get('focal_x', 50)}% {photo.get('focal_y', 50)}%"

        # On-brand copy, grounded only in the real stats/description above
        region_state, region_country = fallback_queries
        copy = blurb_writer.write_copy(
            region_display, angle_label, trails,
            region_state=region_state, region_country=region_country)
    except ConfigError:
        raise
    except RuntimeError as e:
        e.region_path = region_path
        raise

    slides = [{
        "type": "cover",
        "photo": str(photo_path),
        "photo_object_position": photo_object_position,
        "headline": copy["cover_headline"],
    }]
    for t in trails[:3]:
        slides.append({
            "type": "trail_card",
            "photo": str(photo_path),
            "photo_object_position": photo_object_position,
            "card_w": 520,
            "trail_name": t["trail_name"],
            "difficulty": _difficulty_key(t["difficulty_label"]),
            "distance": t.get("distance") or "—",
            "elevation": t.get("net_elevation") or "—",
            "peak_elevation": t.get("peak_elevation") or "—",
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
        "photo_object_position": photo_object_position,
        "headline": "Find trails like this on RidePal.",
        "subtext": "The app that shows you the best trails to ride no matter where you go.",
        "trail_name": hero["trail_name"],
        "difficulty": _difficulty_key(hero["difficulty_label"]),
        "bikes_ok": True,
        "distance": hero.get("distance") or "—",
        "net_elevation": hero.get("net_elevation") or "—",
        "peak_elevation": hero.get("peak_elevation") or "—",
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

    return {
        "run_id": run_id,
        "region": region_display,
        "angle": f"{hook_word} ({angle_label})" if c["format"] == "ranked_list" else angle_label,
        "trail_names": [t["trail_name"] for t in trails],
        "slides": [f"/output/web/{run_id}/{p.name}" for p in paths],
        "caption": "\n".join(caption_lines),
        "photo_cleared": False,
        "photo_source_page": photo.get("source_page"),
        "photo_source_site": photo.get("source_site"),
        "geometry_found": [bool(t.get("points")) for t in trails],
    }


def run_pipeline():
    """Retries with a different region when a failure is about that
    region's own data (not enough real trails, no verified photo)
    instead of surfacing a raw error on the first miss.
    """
    avoid_regions = set()
    last_error = None
    for _ in range(MAX_ATTEMPTS):
        try:
            return _attempt_pipeline(avoid_regions)
        except ConfigError:
            raise
        except RuntimeError as e:
            region_path = getattr(e, "region_path", None)
            if region_path:
                avoid_regions.add(region_path)
            last_error = e
    raise RuntimeError(
        f"Tried {MAX_ATTEMPTS} different areas and none had enough real data. "
        f"Last error: {last_error}")


def _difficulty_key(label):
    return {
        "Green Circle": "green", "Blue Square": "blue",
        "Black Diamond": "black", "Double Black Diamond": "double_black",
    }.get(label, "blue")


def _load_history_index():
    if HISTORY_INDEX.exists():
        return json.loads(HISTORY_INDEX.read_text())
    return []


def _save_history_entry(result):
    (HISTORY_DIR / f"{result['run_id']}.json").write_text(json.dumps(result, indent=2))
    index = _load_history_index()
    index.append({
        "run_id": result["run_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "region": result["region"],
        "angle": result["angle"],
        "trail_names": result["trail_names"],
        "cover_slide": result["slides"][0] if result["slides"] else None,
    })
    HISTORY_INDEX.write_text(json.dumps(index, indent=2))


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/generate", methods=["POST"])
def api_generate():
    try:
        result = run_pipeline()
        _save_history_entry(result)
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/history")
def api_history():
    return jsonify(list(reversed(_load_history_index())))


@app.route("/api/history/<run_id>")
def api_history_detail(run_id):
    path = HISTORY_DIR / f"{run_id}.json"
    if not path.exists():
        return jsonify({"error": "Not found"}), 404
    return jsonify(json.loads(path.read_text()))


@app.route("/output/web/<path:subpath>")
def serve_output(subpath):
    return send_from_directory(OUTPUT_DIR, subpath)


if __name__ == "__main__":
    # threaded=True: without it, Flask's dev server handles one request
    # at a time, so if a generation hangs, every subsequent click queues
    # silently behind it with no error and no log line -- confirmed this
    # happened during testing.
    app.run(debug=True, port=5055, threaded=True)
