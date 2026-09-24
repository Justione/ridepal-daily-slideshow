"""Picks each day's concept: a real region and a real angle, verified
against ridepal.app's own data before anything gets built on top of it.

This module exists specifically because of the Moab mistake: picking a
region name and just assuming it has enough matching trails produces
posts that are wrong. So every candidate region here gets checked live
(does the page even resolve? how many trails at what difficulty does it
actually have?) before it's used, and if a region doesn't check out, it's
skipped rather than forced.
"""
import json
import random
from datetime import date, datetime
from pathlib import Path

import trail_data

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "state" / "concept_history.json"

# Well-known real MTB destinations. This is a starting seed, not a source
# of truth -- every entry gets its ridepal.app region URL VERIFIED live
# (see resolve_region below) before it's ever used. An entry that 404s or
# comes back empty is skipped for that run, not guessed around.
CANDIDATE_REGIONS = [
    "/trails/canada/british-columbia/district-of-north-vancouver",
    "/trails/canada/british-columbia/whistler",
    "/trails/canada/british-columbia/squamish",
    "/trails/us/utah/moab",
    "/trails/us/utah/park-city",
    "/trails/us/utah/ogden",
    "/trails/us/colorado/fruita",
    "/trails/us/colorado/crested-butte",
    "/trails/us/oregon/bend",
    "/trails/us/washington/bellingham",
    "/trails/us/arizona/sedona",
    "/trails/us/arkansas/bentonville",
    "/trails/us/north-carolina/pisgah-forest",
    "/trails/us/vermont/stowe",
    "/trails/us/california/mammoth-lakes",
    "/trails/us/california/downieville",
    "/trails/us/idaho/sun-valley",
    "/trails/us/west-virginia/davis",
]

# A ranked-list post needs this many real trails at the chosen difficulty
# tier before it's worth doing; otherwise fall back to a single-trail
# angle instead of forcing a list that doesn't exist.
MIN_TRAILS_FOR_LIST = 3

DIFFICULTY_ANGLES = [
    ("double_black", "Double Black Diamond", "the hardest"),
    ("black", "Black Diamond", "the hardest"),
    ("blue", "Blue Square", "flow"),
    ("green", "Green Circle", "beginner-friendly"),
]


def _load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"used_regions": [], "used_trails": []}


def _save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def resolve_region(path, min_trails=MIN_TRAILS_FOR_LIST):
    """Fetches a candidate region path and returns its verified region
    dict, or None if the page doesn't resolve or doesn't have enough
    trails to be useful. Never returns unverified data.
    """
    try:
        region = trail_data.fetch_region(path)
    except Exception:
        return None
    if not region.get("trail_paths"):
        return None
    return region


def pick_region(recent_avoid_days=14, avoid_regions=None):
    """Tries candidate regions in random order until one actually
    resolves with real, sufficient data. Skips anything used in the last
    `recent_avoid_days` so the feed doesn't repeat the same place, plus
    anything in `avoid_regions` (regions that already failed earlier in
    this same generation attempt, e.g. not enough real trails).
    """
    state = _load_state()
    cutoff = date.today().toordinal() - recent_avoid_days
    recently_used = {
        r["region_path"] for r in state["used_regions"]
        if date.fromisoformat(r["date"]).toordinal() > cutoff
    }
    recently_used |= set(avoid_regions or [])

    candidates = [c for c in CANDIDATE_REGIONS if c not in recently_used]
    random.shuffle(candidates)

    for path in candidates:
        region = resolve_region(path)
        if region:
            return path, region
    return None, None


def pick_angle(region, region_path):
    """Given a verified region, picks a difficulty tier that the region
    actually has enough real trails for, and returns the angle plus the
    list of candidate trail paths at that tier (still just paths --
    trail_data.fetch_trail must be called per-trail to get verified stats).

    Since the region-index scrape only gives us difficulty COUNTS (not
    which specific trail paths map to which difficulty), the caller is
    expected to fetch a handful of the region's trail_paths and check
    each one's real difficulty via trail_data.fetch_trail until it has
    enough matches -- this function just decides which tier to aim for.

    DIFFICULTY_ANGLES is ordered hardest to easiest, and this always
    takes the hardest viable tier rather than choosing uniformly at
    random. Easier tiers are almost always viable (there are usually
    more beginner trails than double black diamonds anywhere), so a
    uniform pick let the feed default to beginner content constantly --
    the feed should lean into whatever real extreme terrain a region
    actually has, not whatever's most common.
    """
    mix = region.get("difficulty_mix", {})
    viable = [(key, label, angle) for key, label, angle in DIFFICULTY_ANGLES
              if mix.get(key, 0) >= MIN_TRAILS_FOR_LIST]

    state = _load_state()
    region_name = region_path.rsplit("/", 1)[-1]
    recent_angles = {
        r["difficulty_key"] for r in state["used_regions"]
        if r["region_path"] == region_path
    }
    fresh = [v for v in viable if v[0] not in recent_angles]
    pool = fresh or viable

    if pool:
        return pool[0]

    # No tier has enough trails for a ranked list -- fall back to a
    # single-trail deep dive instead of forcing a list that doesn't exist.
    return None


def record_use(region_path, difficulty_key, trail_names):
    state = _load_state()
    state["used_regions"].append({
        "date": date.today().isoformat(),
        "region_path": region_path,
        "difficulty_key": difficulty_key,
    })
    state["used_trails"].extend([
        {"date": date.today().isoformat(), "trail": t} for t in trail_names
    ])
    # keep the file from growing forever
    state["used_regions"] = state["used_regions"][-200:]
    state["used_trails"] = state["used_trails"][-500:]
    _save_state(state)


def select_trails(region, difficulty_key, count=3, max_checks=20):
    """Samples real trail paths from the region's own verified list and
    fetches each one's real stats until `count` trails matching the
    target difficulty are found. Every returned trail has been fetched
    live from ridepal.app -- nothing here is inferred or guessed, since
    the region index only gives difficulty COUNTS, not which path is
    which difficulty.
    """
    state = _load_state()
    recently_used_names = {t["trail"] for t in state["used_trails"]}

    paths = list(region["trail_paths"])
    random.shuffle(paths)

    matches = []
    checked = 0
    for path in paths:
        if checked >= max_checks or len(matches) >= count:
            break
        checked += 1
        try:
            trail = trail_data.fetch_trail(path)
        except Exception:
            continue
        if not trail or not trail.get("difficulty_label"):
            continue
        if DIFFICULTY_LABEL_TO_KEY_LOOKUP.get(trail["difficulty_label"]) != difficulty_key:
            continue
        if trail["trail_name"] in recently_used_names:
            continue
        if any(trail["trail_name"] == m["trail_name"] for m in matches):
            continue  # same trail listed under more than one path/segment
        matches.append(trail)

    return matches


DIFFICULTY_LABEL_TO_KEY_LOOKUP = {
    "Green Circle": "green",
    "Blue Square": "blue",
    "Black Diamond": "black",
    "Double Black Diamond": "double_black",
}


def choose_concept(avoid_regions=None):
    """Top-level entry point: returns a dict describing today's concept,
    or raises if no candidate region could be resolved at all (should be
    rare given the seed list, but this must never fall back to guessing).

    `avoid_regions`: region paths to skip, e.g. ones that already failed
    earlier in this same generation attempt.
    """
    region_path, region = pick_region(avoid_regions=avoid_regions)
    if not region:
        raise RuntimeError(
            "No candidate region resolved with real data -- add more "
            "verified region paths to CANDIDATE_REGIONS rather than "
            "falling back to an unverified guess."
        )

    angle = pick_angle(region, region_path)
    if angle is None:
        return {
            "format": "single_trail",
            "region_path": region_path,
            "region": region,
        }

    difficulty_key, difficulty_label, hook_word = angle
    return {
        "format": "ranked_list",
        "region_path": region_path,
        "region": region,
        "difficulty_key": difficulty_key,
        "difficulty_label": difficulty_label,
        "hook_word": hook_word,
    }


if __name__ == "__main__":
    concept = choose_concept()
    print(json.dumps({k: v for k, v in concept.items() if k != "region"}, indent=2))
    print("region trail count:", concept["region"]["total_trails"])
    print("region difficulty mix:", concept["region"]["difficulty_mix"])
