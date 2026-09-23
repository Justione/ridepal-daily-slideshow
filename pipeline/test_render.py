"""Phase 1 validation run, take 6: every trail is now verified real (cross
-checked against ridepal.app AND OpenStreetMap's named-way data for exact
GPS geometry), all three are actually in the same real place (District of
North Vancouver, BC -- confirmed via ridepal.app's own regional trail list,
which shows 27 real double black diamond trails there), and the map/line
for each slide is real satellite imagery of that trail's real location with
its real GPS shape projected onto it -- not a reused generic crop with a
random line.

Porcupine (Ogden, UT) is NOT used here: it's real and its stats are
verified, but we don't have OSM geometry for it yet, and it's a different
region from the other three anyway, so mixing it into this North Vancouver
post would repeat the exact accuracy mistake that prompted this rebuild.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import render_carousel
from real_trail_data import BOOGIE_MAN, SUICIDE_JIMMY, NEURALYZER

ROOT = Path(__file__).resolve().parent.parent
PHOTOS = ROOT / "assets" / "test-photos"

slides = [
    {
        "type": "cover",
        "photo": str(PHOTOS / "unsplash_whistler_jump.jpg"),  # Dylan Collette, Whistler BC -- real modern rider, real action, right region
        "kicker": "NORTH VANCOUVER, BC",
        "headline": "3 of the hardest MTB trails in North Vancouver",
    },
    {
        "type": "trail_card",
        "photo": str(PHOTOS / "unsplash_forest_ride_1.jpg"),  # Tim Foster -- same photographer RidePal's own homepage already credits
        "card_w": 520,
        **BOOGIE_MAN,
    },
    {
        "type": "trail_card",
        "photo": str(PHOTOS / "unsplash_whistler_jump.jpg"),
        "card_w": 520,
        **SUICIDE_JIMMY,
    },
    {
        "type": "app_full_bleed",
        "photo": str(PHOTOS / "unsplash_forest_ride_1.jpg"),
        "headline": "Find trails like this on RidePal.",
        "subtext": "The app that shows you the best trails to ride no matter where you go.",
        "bikes_ok": True,
        "surface": BOOGIE_MAN["surface"],
        "net_elevation": BOOGIE_MAN["elevation"],
        **{k: v for k, v in BOOGIE_MAN.items() if k not in ("elevation", "surface", "region", "blurb")},
    },
]

if __name__ == "__main__":
    out_dir = ROOT / "output" / "phase1-test"
    paths = render_carousel(slides, out_dir)
    for p in paths:
        print("rendered", p)
