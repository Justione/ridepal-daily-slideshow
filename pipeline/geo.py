"""Turns a real trail's GPS point list into (a) a satellite image fetched
for that exact location and (b) an SVG path in the same coordinate space,
so the rendered line is the real trail's real shape sitting on real
imagery of the real place -- not a generic crop with a random line drawn
over it.
"""
import math
import urllib.request
from pathlib import Path

ESRI_EXPORT_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
    "MapServer/export"
)


def _bbox_for_points(points, target_aspect, padding_ratio=0.45):
    """Bounding box (min_lat, min_lon, max_lat, max_lon) around the trail,
    padded so the line doesn't run edge to edge, and stretched on whichever
    axis is needed so its real-world aspect ratio exactly matches
    target_aspect (width/height) -- this way the satellite image we fetch
    for it can fill the render container with no object-fit cropping, so
    our point projection stays pixel-accurate.
    """
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    lat_span = max_lat - min_lat or 0.001
    lon_span = max_lon - min_lon or 0.001
    lat_pad = lat_span * padding_ratio
    lon_pad = lon_span * padding_ratio
    min_lat -= lat_pad
    max_lat += lat_pad
    min_lon -= lon_pad
    max_lon += lon_pad
    lat_span = max_lat - min_lat
    lon_span = max_lon - min_lon

    mean_lat = (min_lat + max_lat) / 2
    meters_per_lon_deg = math.cos(math.radians(mean_lat))
    lon_span_real = lon_span * meters_per_lon_deg
    current_aspect = lon_span_real / lat_span

    if current_aspect < target_aspect:
        needed_lon_span_real = lat_span * target_aspect
        needed_lon_span = needed_lon_span_real / meters_per_lon_deg
        extra = (needed_lon_span - lon_span) / 2
        min_lon -= extra
        max_lon += extra
    else:
        needed_lat_span = lon_span_real / target_aspect
        extra = (needed_lat_span - lat_span) / 2
        min_lat -= extra
        max_lat += extra

    return min_lat, min_lon, max_lat, max_lon


def _fetch_bbox_image(min_lat, min_lon, max_lat, max_lon, out_path, target_aspect):
    px_w = 1200
    px_h = round(px_w / target_aspect)
    url = (
        f"{ESRI_EXPORT_URL}?bbox={min_lon},{min_lat},{max_lon},{max_lat}"
        f"&bboxSR=4326&size={px_w},{px_h}&format=png32&f=image"
    )
    out_path = Path(out_path)
    urllib.request.urlretrieve(url, out_path)


def fetch_satellite_for_trail(points, out_path, target_w, target_h, padding_ratio=0.45):
    """Fetches a real Esri World Imagery satellite image sized so its real
    -world aspect ratio matches target_w/target_h exactly, centered and
    padded around the trail. Returns the bbox used (for point projection).
    """
    target_aspect = target_w / target_h
    bbox = _bbox_for_points(points, target_aspect, padding_ratio)
    _fetch_bbox_image(*bbox, out_path, target_aspect)
    return bbox


def fetch_satellite_for_point(lat, lon, out_path, target_w, target_h, radius_deg=0.012):
    """Same idea, but for a trail that has real stats (and therefore a
    real lat/lon from ridepal.app) but no OSM line geometry yet -- gives
    it real satellite imagery of its real location instead of leaving the
    map area blank, even though the exact line can't be drawn accurately.
    """
    target_aspect = target_w / target_h
    points = [(lat - radius_deg, lon - radius_deg), (lat + radius_deg, lon + radius_deg)]
    bbox = _bbox_for_points(points, target_aspect, padding_ratio=0.0)
    _fetch_bbox_image(*bbox, out_path, target_aspect)
    return bbox


def project_points_to_svg_path(points, bbox, viewbox_w, viewbox_h,
                                margin=0.26, cross_band=(0.48, 0.80)):
    """Projects real (lat, lon) points into the given viewBox's pixel
    coordinate space (north-up, matching how the satellite image was
    fetched for the same bbox), and emits a straight-segment SVG path --
    a real GPS trace is a polyline, not a smooth curve, so this keeps the
    slightly organic, hand-traced look that makes it read as real.

    The flat 0..viewbox_w x 0..viewbox_h mapping is NOT what ends up
    visible on screen: render.py's map3d CSS puts this plane through a
    bottom-anchored rotateX + scale, which foreshortens the top of the
    viewBox far more than the bottom (and needs a big overscan to cover
    the top edge). A trail centered in flat space visibly lands crushed
    into the upper portion of the tilted result, and edge-hugging points
    can end up clipped. So after the flat projection we re-fit it into
    the same safe inset rectangle the procedural placeholder line uses --
    margin on the (wider) horizontal axis, cross_band biased toward the
    bottom half on the vertical axis -- which is the region empirically
    confirmed to survive that transform with the start and end still
    visible. This does not change the trail's shape, only where in the
    frame that shape sits.
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    lat_span = max_lat - min_lat
    lon_span = max_lon - min_lon

    def proj(lat, lon):
        x = (lon - min_lon) / lon_span * viewbox_w
        y = (max_lat - lat) / lat_span * viewbox_h
        return x, y

    flat = [proj(lat, lon) for lat, lon in points]

    # Fit the trail's own tight extent (not the padded bbox, which can sit
    # off-center inside it depending on the trail's real shape) into the
    # safe zone, uniformly scaled so it isn't stretched, then centered --
    # this is what actually guarantees "centered, start and end visible"
    # regardless of how lopsided the real geometry happens to be.
    xs = [p[0] for p in flat]
    ys = [p[1] for p in flat]
    trail_w = max(xs) - min(xs) or 1
    trail_h = max(ys) - min(ys) or 1

    safe_w = viewbox_w * (1 - 2 * margin)
    safe_h = viewbox_h * (cross_band[1] - cross_band[0])
    scale = min(safe_w / trail_w, safe_h / trail_h)

    scaled_w = trail_w * scale
    scaled_h = trail_h * scale
    offset_x = viewbox_w * margin + (safe_w - scaled_w) / 2
    offset_y = viewbox_h * cross_band[0] + (safe_h - scaled_h) / 2

    min_x, min_y = min(xs), min(ys)

    def refit(x, y):
        nx = offset_x + (x - min_x) * scale
        ny = offset_y + (y - min_y) * scale
        return nx, ny

    safe = [refit(x, y) for x, y in flat]

    d = f"M {safe[0][0]:.1f} {safe[0][1]:.1f} "
    d += " ".join(f"L {x:.1f} {y:.1f}" for x, y in safe[1:])
    return d
