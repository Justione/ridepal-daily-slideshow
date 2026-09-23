"""End-to-end pipeline test using a fresh, different region (Ogden, UT)
picked live by concept.py -- proves the daily flow generalizes beyond the
North Vancouver example that was hand-tuned during template validation.

Middle Bowl has real OSM geometry (fetched via browser per the playbook).
Jumpoff Canyon Trail and Needles deliberately have no `points` attached,
to prove the documented fallback (procedural placeholder line) still
works cleanly when a trail has no OSM match yet.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import render_carousel

ROOT = Path(__file__).resolve().parent.parent
PHOTOS = ROOT / "assets" / "daily-photos"
PHOTO = str(PHOTOS / "2026-09-23_ogden_test.jpg")

MIDDLE_BOWL_POINTS = [
    (41.1950058, -111.8676053), (41.1949592, -111.867455), (41.1949592, -111.8673973),
    (41.1949681, -111.8673499), (41.1949793, -111.8673218), (41.1950316, -111.8672582),
    (41.195055, -111.8671754), (41.1950605, -111.867094), (41.1950806, -111.8670437),
    (41.1950717, -111.8669993), (41.195055, -111.866986), (41.1950427, -111.8669919),
    (41.1950349, -111.8670333), (41.1950127, -111.8671561), (41.1949891, -111.8672113),
    (41.1948997, -111.8672776), (41.1947861, -111.8673608), (41.1946551, -111.86735),
    (41.194538, -111.8672615), (41.1944431, -111.8672535), (41.1942998, -111.8671462),
    (41.1942252, -111.8670577), (41.1941444, -111.8669021), (41.1938619, -111.8664595),
    (41.1937852, -111.8664032), (41.1936257, -111.866084), (41.1935833, -111.8660116),
    (41.1935409, -111.8659928), (41.1934905, -111.8658802), (41.1934481, -111.8655261),
    (41.1934542, -111.8654725), (41.1934743, -111.8654269), (41.193487, -111.8653798),
    (41.1934905, -111.8653679), (41.1934723, -111.8652472), (41.1934521, -111.8651801),
    (41.1934582, -111.8650997), (41.1934784, -111.865046), (41.1935006, -111.8650353),
    (41.1935208, -111.8650433), (41.193531, -111.8650715), (41.1935288, -111.8651372),
    (41.1935631, -111.8651908), (41.1936802, -111.8653115), (41.1937246, -111.8653759),
    (41.1937569, -111.8653813), (41.1937831, -111.8653706), (41.1938074, -111.8653303),
    (41.1938296, -111.8652472), (41.1938296, -111.8651828), (41.1938215, -111.8651211),
    (41.1937932, -111.8650594), (41.1937327, -111.8649816), (41.193654, -111.8649629),
    (41.1936015, -111.8648234), (41.1936015, -111.8647402), (41.1935934, -111.8646893),
    (41.1935571, -111.8646678), (41.1935187, -111.864641), (41.1935167, -111.8645793),
    (41.1934986, -111.8645337), (41.1934501, -111.8644908), (41.1934017, -111.8643486),
    (41.1933472, -111.8642869), (41.1931554, -111.8637237), (41.1930848, -111.8634045),
    (41.1930626, -111.8631041), (41.1931009, -111.8628788), (41.1931616, -111.862805),
    (41.19321, -111.8627594), (41.1932543, -111.8625784), (41.1933976, -111.8623611),
    (41.1934442, -111.8623383), (41.1934663, -111.8622297), (41.1935692, -111.8621331),
    (41.1937165, -111.8617683), (41.1937085, -111.8615672), (41.19387, -111.8606566),
    (41.1938901, -111.8605989), (41.1939527, -111.8605104), (41.1939628, -111.8603495),
    (41.1940052, -111.8602583), (41.1940576, -111.8602127), (41.1940839, -111.8601832),
    (41.1940819, -111.860151), (41.1940617, -111.8601134), (41.1940314, -111.8601215),
    (41.1939831, -111.8601522),
]

slides = [
    {
        "type": "cover",
        "photo": PHOTO,
        "kicker": "OGDEN, UTAH",
        "headline": "3 flowy MTB trails in Ogden worth a lap",
    },
    {
        "type": "trail_card",
        "photo": PHOTO,
        "card_w": 520,
        "trail_name": "Middle Bowl",
        "difficulty": "blue",
        "distance": "1.8 mi",
        "elevation": "—",
        "peak_elevation": "—",
        "est_time": "19 min",
        "points": MIDDLE_BOWL_POINTS,
        "blurb": "1.8 miles of real flow right above town, rated blue square top to bottom.",
    },
    {
        "type": "trail_card",
        "photo": PHOTO,
        "card_w": 520,
        "trail_name": "Jumpoff Canyon Trail",
        "difficulty": "blue",
        "distance": "0.7 mi",
        "elevation": "—",
        "peak_elevation": "—",
        "est_time": "8 min",
        "lat": 41.266480099999995, "lon": -111.94542775,
        # no `points` on purpose -- tests the documented fallback path
        # (real lat/lon still gets real satellite imagery, just with a
        # placeholder line instead of a fabricated "real" shape)
        "blurb": "Short at 0.7 miles, but a clean blue square line if you're short on time.",
    },
    {
        "type": "app_full_bleed",
        "photo": PHOTO,
        "headline": "Find trails like this on RidePal.",
        "subtext": "The app that shows you the best trails to ride no matter where you go.",
        "trail_name": "Middle Bowl",
        "difficulty": "blue",
        "bikes_ok": True,
        "distance": "1.8 mi",
        "net_elevation": "—",
        "peak_elevation": "—",
        "est_time": "19 min",
        "surface": "Ground",
        "points": MIDDLE_BOWL_POINTS,
    },
]

if __name__ == "__main__":
    out_dir = ROOT / "output" / "daily-test-ogden"
    paths = render_carousel(slides, out_dir)
    for p in paths:
        print("rendered", p)
