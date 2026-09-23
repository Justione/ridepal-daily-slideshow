# RidePal Daily Slideshow — Run Playbook

You are generating one day's Instagram carousel for RidePal, following the
validated template in this project. Everything here has already been
built and approved by Justin; your job today is to run it with a fresh,
real trail concept. Follow every step — do not skip the verification
steps to save time, and never invent a fact that isn't confirmed by a
live source.

Project root: `~/ridepal-daily-slideshow/`. Python env: `.venv` (activate
with `source .venv/bin/activate` from the project root before running
anything). All pipeline code is in `pipeline/`.

## The one hard rule

**Never fabricate trail data.** Distance, difficulty, time, surface,
description, and location must always come from a live `trail_data.py`
fetch of the real ridepal.app page. If a number isn't available (net/peak
elevation is often blank on the public site), show "—" exactly like the
real site does — never invent a plausible-looking number. This is the
rule that got broken once already (the Moab mistake) and must not break
again.

## Step 1 — Pick and verify today's concept

```bash
cd ~/ridepal-daily-slideshow && source .venv/bin/activate
python3 pipeline/concept.py
```

This picks a real region from the candidate list, live-verifies it
resolves on ridepal.app with real trail data, and picks a difficulty
angle the region actually has enough trails for (falling back to
`single_trail` format if no tier has 3+ trails). Read the printed output.

If `format` is `ranked_list`: call `concept.select_trails(region,
difficulty_key, count=3)` in a Python shell or script to get 3 real,
unique, verified trails at that difficulty (dedupes and re-fetches
automatically). If `format` is `single_trail`: pick one real trail from
`region["trail_paths"]` via `trail_data.fetch_trail`, favoring one with a
real, specific `description` field (richer for the blurb) over a generic
one.

Each trail dict now has: `trail_name`, `distance`, `difficulty_label`,
`est_time`, `surface`, `description`, `lat`, `lon`, `region`, `url`.

## Step 2 — Get each trail's real GPS line (needs the browser)

`ridepal.app`'s own trail-line data isn't exposed on the public page, but
OpenStreetMap often has the same named trail mapped with real geometry —
confirmed to work for every trail checked so far in BC and Utah. This
step **must** go through the browser's `javascript_tool` — the Overpass
API returns 406 to `curl`/`requests` regardless of headers (confirmed),
but works fine from a real browser `fetch()`.

For each trail, using the browser (`mcp__Claude_Browser__javascript_tool`,
on any open tab):

```js
async function q(query, retries=5) {
  for (let i=0;i<retries;i++){
    try {
      const res = await fetch("https://overpass-api.de/api/interpreter", { method: "POST", body: "data=" + encodeURIComponent(query) });
      return JSON.parse(await res.text());
    } catch(e) { await new Promise(r=>setTimeout(r,3000)); }
  }
  return null;
}
// use the trail's lat/lon from Step 1 to build a tight bbox (±0.08° is plenty)
const data = await q(`[out:json][timeout:25];way["name"~"TRAIL_NAME_HERE",i](LAT_MIN,LON_MIN,LAT_MAX,LON_MAX);out geom;`);
JSON.stringify(data.elements.map(e => ({id: e.id, tags: e.tags, points: e.geometry.length})))
```

**Verify before trusting it**: check that `tags.name` matches the trail
name closely and, if available, that `tags.surface` matches the surface
ridepal.app reported in Step 1. If nothing matches, this trail has no OSM
geometry yet — that's fine, just don't attach a `points` field for it
(the render pipeline already has a documented fallback: it uses a
procedural placeholder line instead of a fabricated real one, exactly
like the Porcupine trail in testing). Don't force a match that isn't
really the same trail.

Once you've found the right way, fetch its full geometry the same way
(`way(ID);out geom;`) and collect the `[{lat, lon}, ...]` array — this
becomes that trail's `points` list, as `(lat, lon)` tuples, matching the
format in `pipeline/real_trail_data.py`.

## Step 3 — Source a real, high-quality regional photo (needs the browser)

Per Justin's direction: **do not** try to find a photo of the exact
trail — that's too hard to find reliably. Instead find a **high-quality,
professional-looking action photo of a real rider on a modern bike**,
from the same general area or at minimum the same country, doing
something that reads as genuinely technical/exciting. No old-looking
photos, no random amateur shots, no antique bikes — this must look like
it could run on a real MTB brand's Instagram.

Search Unsplash (`unsplash.com/s/photos/mountain-biking-{region-or-country}`)
in the browser. Prefer, in order:
1. A shot from the exact city/region if one exists and looks professional.
2. A shot from the same province/state.
3. A shot from the same country (e.g., any real Canada shot for a BC
   post) — this is an acceptable, expected fallback per Justin.

Open the photo's page, confirm it says **"Free to use under the Unsplash
License"** (all Unsplash photos are, but confirm), note the photographer
and location for your own records, then download via the "Download free"
link:

```bash
curl -sL "https://unsplash.com/photos/PHOTO_ID/download?force=true" -o assets/daily-photos/YYYY-MM-DD_slug.jpg
```

Get 1–2 distinct photos per post (cover + one reused across trail cards
is fine, matching what shipped in testing).

## Step 4 — Write the blurbs

For each trail slide, write: the trail name (rendered as "{Name} Trail"
in the template automatically) and a one-sentence blurb explaining what
makes it notable, tying back to the cover hook. Ground every blurb in
the trail's real `description` field from Step 1 when one exists —
paraphrase it, don't invent beyond it. If there's no description, write
a short factual line built only from the confirmed stats (distance,
difficulty, name) — nothing speculative.

Follow the RidePal writing rules (`ridepal-marketing` skill): no dashes,
no emojis, no hashtags, no corporate language, sounds like a rider
talking to a rider. Cover hook should follow the pattern validated in
testing: "N of the [angle] MTB trails in [region]" for ranked lists.

## Step 5 — Render

Write a small script (same shape as `pipeline/test_render.py` — copy it
as a starting point) that builds the slide spec list: one `cover` slide,
one `trail_card` per trail (with `points` from Step 2 when available,
`photo` from Step 3, `blurb` from Step 4), and one `app_full_bleed` slide
featuring whichever trail has the richest real data. Then:

```python
from render import render_carousel
paths = render_carousel(slides, out_dir="../output/YYYY-MM-DD")
```

## Step 6 — Verify before sending

Open each rendered PNG and check: trail line is centered with visible
start/end (not clipped), no UI overlap, stats match what you fetched in
Step 1 exactly, no placeholder or fabricated text anywhere.

## Step 7 — Deliver and record

Send the rendered slides to Justin with `SendUserFile`, with a short
caption noting the region, the angle, and which photos still need his
manual permission check-in if any came from a source other than
Unsplash's pre-cleared license (shouldn't happen if Step 3 was followed,
but call it out explicitly if it did).

Then record what was used so tomorrow's run doesn't repeat it:

```python
import concept
concept.record_use(region_path, difficulty_key, [t["trail_name"] for t in trails])
```

Remember: **Justin posts manually.** This pipeline never posts to
Instagram itself — its job ends at delivering the images and caption to
him here.

## Important: this runs in a fresh cloud checkout every time

Each scheduled run clones this repo fresh — nothing persists on disk
between days except what's committed to git. `state/concept_history.json`
(repeat-avoidance) only works across days if you commit and push it back
at the end of every run:

```bash
git add state/concept_history.json output/
git commit -m "Daily slideshow: $(date +%Y-%m-%d) - <region>, <angle>"
git push
```

Commit the rendered output images too (`output/`), even though
`.gitignore` normally excludes it for local dev — for a cloud run this is
the only durable record of what was generated, in case `SendUserFile`
delivery doesn't land for some reason. Use `git add -f output/` if
`.gitignore` blocks it.
