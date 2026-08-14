# Deploying

`.github/workflows/deploy.yml` builds `mockups/out` and publishes it to GitHub Pages on
every push to `main`. Nothing here touches the live site until you point it at a repo that
owns the live domain.

## Test it first, three ways

Listed cheapest-first. **Option 1 needs no DNS and cannot affect www.steinmetzlab.net.**

### 1. A separate repo, on a github.io sub-path  *(recommended first step)*

Create `SteinmetzLab/website-v2`, push this folder to `main`, then in **Settings → Pages**
set *Source* to **GitHub Actions**. The site appears at:

```
https://steinmetzlab.github.io/website-v2/
```

The existing site is untouched — it is a different repo with its own Pages deployment. Our
links are all relative, so they work fine under a sub-path.

### 2. `test.steinmetzlab.net`

Same repo as option 1, plus:

- a DNS **CNAME** record at your registrar: `test` → `steinmetzlab.github.io`
- **Settings → Pages → Custom domain** in the test repo: `test.steinmetzlab.net`

GitHub writes a `CNAME` file into the repo when you do this. A given hostname can be
claimed by only one repo, and `test.` is a different hostname from `www.`, so this does not
disturb the live site. Wait for the certificate to issue before enabling *Enforce HTTPS*.

### 3. `www.steinmetzlab.net/test`

Possible, but it means putting the new site inside the **live** repo
(`SteinmetzLab.github.io`), because a path under a domain is served by whichever repo owns
that domain. You would add the built files under `/test/` there. It works and needs no DNS,
but it mixes the new site into the repo that is serving the old one, and Jekyll builds that
repo — so you would also need to keep the folder out of Jekyll's way. I would use option 1
or 2 instead.

## Going live

The plan is to replace the contents of `SteinmetzLab/SteinmetzLab.github.io` — the repo
that owns `www.steinmetzlab.net` — with this project. The old Jekyll site stays in that
repo's git history, which is the only copy of it, so nothing is lost.

Two things about that repo are not what this workflow expects, and both matter:

- **Its default branch is `master`, not `main`.** The workflow triggers on both.
- **Its Pages source is "Deploy from a branch", so GitHub runs Jekyll over it.** This
  project is already built; Jekyll would produce nothing usable. The source has to be
  **Settings → Pages → Build and deployment → Source: GitHub Actions**. That is a click in
  the browser; there is no way to set it from a workflow. `actions/configure-pages` will
  *not* do it — with `enablement: true` it creates a Pages site if one is missing, but when
  a site already exists it only reads the config back, it never changes the build type.

Order, to keep the downtime to the length of one workflow run:

1. Flip **Settings → Pages → Source** to **GitHub Actions**. The last deployment keeps
   being served while you do this.
2. Push this project to that repo's `master`, replacing the Jekyll tree. The push runs the
   workflow, which builds and deploys in two or three minutes.
3. Check `https://www.steinmetzlab.net/` **in a browser that has been there before**, not
   just a fresh incognito window — see the service worker note below, which is the one
   failure mode that only shows up for returning visitors.

Keep the custom domain setting on that repo. A hostname can be claimed by exactly one
repository, and the workflow writes a `CNAME` file into the artifact only when it is
running in `SteinmetzLab/SteinmetzLab.github.io`, so test deployments elsewhere cannot
take the domain away from it.

### The old site's service worker

The Jekyll theme registered a service worker at `/sw.js` whose precache list included `/`
and `/index.html`. Every browser that has ever loaded `www.steinmetzlab.net` still has it
installed and will answer navigations from *its own cache* — so without intervention those
visitors keep seeing the old homepage after launch, indefinitely, with nothing to tell them
the site changed. `mockups/static/sw.js` is a replacement at the same URL that drops every
cache, unregisters itself and reloads the tab. It has to keep shipping; deleting it brings
the problem straight back.

### Old URLs

The Jekyll site's permalinks (`/people/`, `/pubs/`, `/join/`, `/news/`, …) are in search
results and on other labs' pages. `REDIRECTS` in `build.py` turns each into a directory
holding a meta-refresh stub pointing at the new page, and writes a `404.html` for anything
else — the news posts, which lived at `/:title/`, cannot be mapped one to one. Add an entry
to that dict if you find an old URL that is still being linked.

## What the workflow assumes

- `mockups/out` is the whole deployable site. It contains `index.html`, which `build.py`
  writes as a copy of `HOMEPAGE` (currently `a2-signal.html`).
- Everything the build reads is committed: `src/`, `data/`, `assets/`. The `tools/` scripts
  that generate assets from lab recordings are **not** run in CI — they need the lab server
  and are run by hand when the underlying data changes.
- The build is deterministic and takes a few seconds.

## Linked assets

The deployed pages link their fonts, clips, portraits and recordings out of `out/assets/`
rather than inlining them as base64. That took the homepage from **2.6 MB to 75 KB** — the
gain is not only the first load but every load after it, because an inlined asset sits
*inside* the HTML and so can never be cached: the same fonts and the same 141-neuron
recording used to be re-downloaded in full on every single page.

- Each file is written under a **content-hashed name** (`raster.83ae5fd9bc.js`). The name
  changes whenever the bytes do, so a cached copy can never go stale and the assets never
  need to expire.
- The recordings and the shared engine are linked **classic scripts**, which the browser
  runs in document order. `RASTER` and `SL` are therefore already defined by the time a
  page's own inline script runs, exactly as when they were pasted in above it — nothing in
  the page code had to become asynchronous.
- All four typeface families still ship, but a browser only requests a font it actually
  renders, so an A2 page fetches four woff files rather than thirteen.
- Two CI steps defend this. `runpage.js` follows `<script src>`, so a page whose linked
  engine or recording went missing fails the build; and a size gate fails if any deployed
  page grows past 250 KB, which is what an accidental return to inlining would look like.

The older `a-*`, `b-*`, `c-*` and `d-*` comparison mockups still inline everything, via the
`{{DATA:...}}` and `{{JSON:...}}` placeholders. That is deliberate — they exist to be
mailed to somebody as a single file.
