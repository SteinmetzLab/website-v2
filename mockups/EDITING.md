# Editing the site

## The one rule

**Edit `src/` and `data/`. Never edit `out/`.**

`out/*.html` is generated. Every edit there is destroyed by the next build. The build now
refuses to run if it notices you edited a built file, and tells you so — but the fix is
always to move the change into `src/` or `data/` and rebuild.

Then:

```
python build.py
```

## Which page is which

`a2-*` is the live design line and what gets deployed; `index.html` is built as a copy of
`a2-signal.html`. The `a-*` pages are the earlier version kept for comparison, with the
palette/typeface/theme switcher still attached. Edit the `a2-*` files.

| Page | Source |
|---|---|
| Home | `src/a2-signal.html` |
| Publications | `src/a2-publications.html` |
| People and alumni | `src/a2-people.html` |
| News | `src/a2-news.html` |
| Join us | `src/a2-join.html` |
| Contact | `src/a2-contact.html` |
| Teaching | `src/a2-teaching.html` |

## Where does a given piece of text live?

| You want to change | Edit | Why there |
|---|---|---|
| A heading, a lede, the hero sentence, a research question or its subtext, the CTA | `src/a2-signal.html` | One-off prose. Editing it in place lets you put a link or emphasis mid-sentence without escaping anything. |
| Publications | `data/pubs.json` | A list that grows. Adding a paper is one entry; the year headings, filters and counts follow automatically. |
| News | `data/news.json` | Same. Newest first is automatic — the build sorts by date, so put a new entry anywhere in the file. |
| People (current) | `data/people.json` | Same. Order is derived from `group` then `joined`, so a new arrival lands in the right cohort. |
| Alumni | `data/alumni.json` | Same. Sorted by leaving year. Fill in `now` as you learn where someone went; it renders in the accent color. |
| The Open Science lists (datasets, software, hardware) | `data/resources.json` | Same. The section's *heading and lede* are prose and stay in `src/a-signal.html`. |
| Colours, type, spacing, any styling | `src/partials/a-base.css`, `a-page.css`, `palettes.css` | Shared by every page. |
| The header, nav, or footer | `src/partials/a-nav.html`, `a-foot.html` | Shared by every page — change once, all pages follow. |
| How an animation behaves | `src/partials/engine.js` | Shared rendering engine. |

The rule of thumb: **prose in HTML, lists in JSON.** A sentence that appears once belongs
where you can see it in context. A row that will have thirty siblings belongs in a data
file, so that adding the thirty-first is a copy-paste rather than a layout decision.

## Your edits and mine

There is no separate copy of this content anywhere. `src/` and `data/` **are** the site, so
anything you change there is simply what the site says from then on. When you ask me to
change something later I read these files first, so I see your wording and work from it.

The one thing that would lose your work is editing `out/`, which is what the guard above
exists to prevent.

## Files that ship as-is

Anything in a `static/` folder is copied straight into the built site, unchanged, for files
that have to stay real files rather than being inlined as data URIs. Everything in
`assets/` is inlined instead.

## Adding an entry

Every data file has a `_comment` at the top describing its fields. The shortest path is to
copy the entry above the one you want and change the values. JSON is picky about two things:
every entry except the last needs a trailing comma, and strings need straight double quotes.
If the build complains about JSON, it will name the file and the line.

## Rebuilding data-derived assets

These regenerate the *inputs* and are only needed if the underlying recordings or the fit
change — not for ordinary text edits:

```
python tools/make_widefield.py      # widefield SVD  -> assets/widefield_b64.json
python tools/make_raster.py         # spike raster   -> assets/raster_b64.json
python tools/make_psychometric.py   # model fit      -> assets/psychometric.json + review clips
python tools/make_people.py         # face-centered portraits -> assets/people/
python tools/make_videos.py         # review MP4s in video/
```
