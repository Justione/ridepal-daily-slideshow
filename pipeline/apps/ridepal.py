"""RidePal's configuration: brand voice, visual identity, candidate
regions, and activity vocabulary -- the values that make a generated
slideshow specifically RidePal's rather than some other app's.

The generic pipeline (concept's difficulty-tier logic, photo_serper's
search+vision engine, blurb_writer's Claude-calling scaffold, render.py)
takes these as parameters instead of hardcoding them. Only RidePal
exists today -- this file is the one place that says so. Adding a
second app later means writing a new config module shaped like this
one (plus its own trail-data source, since that part is tied to the
specific site being scraped), not touching the generic pipeline.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

APP_KEY = "ridepal"
DISPLAY_NAME = "RidePal"
LOGO_PATH = ROOT / "assets" / "logo" / "ridepal-logo-new.png"
BRAND_COLOR = "#32664C"

# What the photo search and the vision quality/action check look for.
ACTIVITY = "mountain biking"
SUBJECT = "mountain biker"
SUBJECT_ACTION = "riding a mountain bike"
PHOTO_SEARCH_SUFFIX = "mountain biker riding trail"

# Real, well-known MTB destinations. A starting seed, not a source of
# truth -- concept.py verifies every one live against ridepal.app before
# it's ever used, and skips anything that doesn't check out.
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

CTA_HEADLINE = "Find trails like this on RidePal."
CTA_SUBTEXT = "The app that shows you the best trails to ride no matter where you go."
CAPTION_CTA = "Find trails like this on RidePal."

BRAND_VOICE_RULES = """- No dashes of any kind (no -, no --, no em dash).
- No emojis.
- No hashtags.
- No corporate language ("revolutionary", "ultimate", "next level", "game-changer").
- Sounds like a rider talking to another rider, not a brand talking to a customer. Matter-of-fact, slightly punchy, grounded in real riding."""

# Picked at random per call so headline structure actually varies across
# generations instead of the model converging on one "safe" shape when
# just given examples to draw from (confirmed: it converged anyway).
HEADLINE_STYLES = [
    "a numbered list hook, e.g. 'N of the hardest MTB trails in <city>'",
    "a superlative claim about danger or difficulty, e.g. 'The deadliest MTB trails in <state>' -- only if the real difficulty actually supports that framing",
    "a possessive, place-first hook, e.g. '<city>'s gnarliest singletrack'",
    "a stakes or warning hook, e.g. 'MTB trails in <region> that don't forgive mistakes'",
    "an exclusivity or challenge hook, e.g. 'N trails only advanced riders should try in <city>'",
    "a superlative claim at the state or country level, e.g. 'The most technical singletrack in <state>'",
]
