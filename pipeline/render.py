"""Renders slide specs (Python dicts) into 1080x1350 PNG carousel slides.

Uses Jinja2 to fill the HTML templates in templates/, then Playwright
(headless Chromium) to screenshot each rendered page at exact pixel size,
so CSS shadows/gradients/rounded corners come out pixel-accurate instead
of hand-composited.
"""
import random
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

import geo

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
BASE_CSS = ROOT / "assets" / "css" / "base.css"
LOGO = ROOT / "assets" / "logo" / "ridepal-logo-new.png"
MAP_CACHE_DIR = ROOT / "assets" / "generated-maps"

FRAME_W = 1080
FRAME_H = 1350

_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))


def _trail_line_path(width, height, seed=None, margin=0.13, cross_band=(0.16, 0.84)):
    """Generates an SVG path that reads as a real trail line: a clear
    directional route across the frame (not a wandering blob confined to
    a box) with natural meander and, most of the time, one switchback
    hairpin -- the visual signature that makes a line recognizable as a
    trail rather than an abstract squiggle. Orientation follows the
    container's own aspect ratio (a portrait map card flows top-to-bottom,
    a landscape map header flows left-to-right), matching how routes are
    actually drawn in the reference screenshots.

    margin/cross_band both need to be generous when the caller renders
    this on top of a CSS 3D-tilted plane (scale + rotateX): that transform
    crops well inside the nominal viewBox, so a path that looks safely
    inset in flat 2D coordinates can still end up clipped at the visible
    edges once the tilt is applied.
    """
    rng = random.Random(seed)
    vertical = height > width
    long_dim, short_dim = (height, width) if vertical else (width, height)
    lo, hi = short_dim * cross_band[0], short_dim * cross_band[1]

    n = rng.randint(5, 7)
    primary = [long_dim * (margin + (1 - 2 * margin) * i / (n - 1)) for i in range(n)]
    cross = [(lo + hi) / 2]
    step = (hi - lo) * 0.35
    for _ in range(n - 1):
        nxt = cross[-1] + rng.uniform(-step, step)
        nxt = max(lo, min(hi, nxt))
        cross.append(nxt)
    pts = list(zip(cross, primary)) if vertical else list(zip(primary, cross))

    if rng.random() < 0.65 and n >= 5:
        idx = rng.randint(2, n - 3)
        x0, y0 = pts[idx]
        side = rng.choice([-1, 1])
        clamp = lambda v: max(lo, min(hi, v))
        if vertical:
            hp1 = (clamp(x0 + side * (hi - lo) * 0.4), y0 - long_dim * 0.035)
            hp2 = (clamp(x0 + side * (hi - lo) * 0.08), y0 + long_dim * 0.06)
        else:
            hp1 = (x0 - long_dim * 0.035, clamp(y0 + side * (hi - lo) * 0.4))
            hp2 = (x0 + long_dim * 0.06, clamp(y0 + side * (hi - lo) * 0.08))
        pts = pts[:idx] + [hp1, hp2] + pts[idx:]

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    d = f"M {xs[0]:.1f} {ys[0]:.1f} "
    for i in range(1, len(xs)):
        cx = (xs[i - 1] + xs[i]) / 2
        cy = (ys[i - 1] + ys[i]) / 2
        d += f"Q {xs[i-1]:.1f} {ys[i-1]:.1f} {cx:.1f} {cy:.1f} "
    d += f"T {xs[-1]:.1f} {ys[-1]:.1f}"
    return d


def _elevation_chart(width, height, seed=None, points=40):
    """Generates a jagged elevation-profile line (not smooth like the trail
    line), plus a closed area path for the gradient fill beneath it,
    mimicking the real app's elevation chart.
    """
    rng = random.Random(seed)
    trend = rng.choice([-1, 1]) * rng.uniform(0.45, 0.85)
    ys = []
    y = height * (0.25 if trend < 0 else 0.7)
    for i in range(points):
        y += trend * (height / points) + rng.uniform(-height * 0.05, height * 0.05)
        y = max(height * 0.08, min(height * 0.92, y))
        ys.append(y)
    xs = [width * i / (points - 1) for i in range(points)]

    line = f"M {xs[0]:.1f} {ys[0]:.1f} " + " ".join(f"L {x:.1f} {y:.1f}" for x, y in zip(xs[1:], ys[1:]))
    area = line + f" L {xs[-1]:.1f} {height} L {xs[0]:.1f} {height} Z"
    return line, area


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _real_map_and_trace(spec, viewbox_w, viewbox_h, cache_key_suffix="",
                         margin=0.28, cross_band=(0.58, 0.85)):
    """When the spec carries real GPS points (verified against ridepal.app
    and OpenStreetMap), fetches real satellite imagery for that trail's
    actual location and projects the real geometry into the given viewBox.

    When there's no real line geometry yet but the trail does have real
    lat/lon (every ridepal.app trail does), still fetch real satellite
    imagery of that real location -- just with the procedural placeholder
    line drawn over it instead of a fabricated "real" shape. Only when
    there's no location data at all does this fall back to no map image,
    which the caller then has to handle (should not happen for any trail
    that came from trail_data.fetch_trail).

    Returns (map_image_path, trace_path_or_None). trace_path is None when
    the caller should generate the procedural line itself.
    """
    MAP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _slug(spec.get("trail_name", "trail")) + cache_key_suffix
    img_path = MAP_CACHE_DIR / f"{key}.png"

    points = spec.get("points")
    if points:
        bbox = geo.fetch_satellite_for_trail(points, img_path, viewbox_w, viewbox_h)
        trace_path = geo.project_points_to_svg_path(
            points, bbox, viewbox_w, viewbox_h, margin=margin, cross_band=cross_band)
        return str(img_path), trace_path

    lat, lon = spec.get("lat"), spec.get("lon")
    if lat is not None and lon is not None:
        geo.fetch_satellite_for_point(lat, lon, img_path, viewbox_w, viewbox_h)
        return str(img_path), None

    return None, None


DIFFICULTY_META = {
    "green": {"shape": "circle", "label": "Green Circle"},
    "blue": {"shape": "square", "label": "Blue Square"},
    "black": {"shape": "diamond", "label": "Black Diamond"},
    "double_black": {"shape": "diamond", "label": "Double Black Diamond"},
}


def _inject_common(spec):
    spec = dict(spec)
    spec.setdefault("base_css", str(BASE_CSS))
    spec.setdefault("logo", str(LOGO))
    difficulty = spec.get("difficulty")
    if difficulty:
        meta = DIFFICULTY_META[difficulty]
        spec.setdefault("difficulty_shape", meta["shape"])
        spec.setdefault("difficulty_label", meta["label"])
    trail_name = spec.get("trail_name")
    if trail_name:
        already_has_trail = trail_name.strip().lower().endswith("trail")
        spec.setdefault("display_trail_name", trail_name if already_has_trail else f"{trail_name} Trail")
    return spec


def render_slide(spec, out_path, page):
    """Renders one slide spec dict to a PNG at out_path using an open Playwright page."""
    spec = _inject_common(spec)
    slide_type = spec["type"]

    if slide_type == "trail_card":
        card_w = spec.setdefault("card_w", 520)
        map_h = spec.setdefault("map_h", round(card_w * 0.95))
        real_img, real_trace = _real_map_and_trace(
            spec, card_w, map_h, cache_key_suffix="-card", margin=0.19, cross_band=(0.60, 0.90))
        if real_img:
            spec.setdefault("map_image", real_img)
        if real_trace:
            spec.setdefault("trace_path", real_trace)
        else:
            spec.setdefault("trace_path", _trail_line_path(
                card_w, map_h, seed=spec.get("trail_name"), margin=0.19, cross_band=(0.60, 0.90)))
    if slide_type == "app_full_bleed":
        pw = spec.setdefault("phone_w", 620)
        phone_top = spec.setdefault("phone_top", 560)
        # The Save/Offline/Drive/Bike There buttons are a sticky floating
        # card in the real app (it stays put while content scrolls behind
        # it), not part of the normal document flow -- so its position is
        # computed relative to the visible crop, not to how much content
        # precedes it.
        phone_pad = pw * 0.026
        visible_bottom_in_screen = (FRAME_H - phone_top) - phone_pad
        bar_h_est = pw * 0.34
        bar_margin = pw * 0.045
        spec.setdefault("sticky_buttons_top", round(visible_bottom_in_screen - bar_h_est - bar_margin))
        map_h = round(pw * 0.64)
        real_img, real_trace = _real_map_and_trace(
            spec, pw, map_h, cache_key_suffix="-hero", margin=0.16, cross_band=(0.42, 0.92))
        if real_img:
            spec.setdefault("map_image", real_img)
        if real_trace:
            spec.setdefault("trace_path_full", real_trace)
        else:
            spec.setdefault("trace_path_full", _trail_line_path(
                pw, map_h, seed=spec.get("trail_name"), margin=0.16, cross_band=(0.42, 0.92)))
        chart_w, chart_h = round(pw * 0.86), round(pw * 0.34)
        line, area = _elevation_chart(chart_w, chart_h, seed=spec.get("trail_name"))
        spec.setdefault("elevation_chart_w", chart_w)
        spec.setdefault("elevation_chart_h", chart_h)
        spec.setdefault("elevation_line_path", line)
        spec.setdefault("elevation_area_path", area)

    template = _env.get_template(f"{slide_type}.html")
    html = template.render(**spec)

    tmp_html = out_path.with_suffix(".html")
    tmp_html.write_text(html)

    page.goto(f"file://{tmp_html}")
    page.wait_for_timeout(150)  # let web fonts settle
    page.screenshot(path=str(out_path))
    tmp_html.unlink()


def render_carousel(slide_specs, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": FRAME_W, "height": FRAME_H})
        for i, spec in enumerate(slide_specs, start=1):
            out_path = out_dir / f"slide_{i}.png"
            render_slide(spec, out_path, page)
            paths.append(out_path)
        browser.close()
    return paths
