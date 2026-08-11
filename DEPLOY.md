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

Once you are happy:

1. Point the workflow at the repo that owns the domain, **or** move the domain to the new
   repo (Settings → Pages → Custom domain: `www.steinmetzlab.net`, and remove it from the
   old repo first — one repo per hostname).
2. Keep the `CNAME` file. GitHub Pages recreates it from the custom-domain setting, but if
   it goes missing the domain stops resolving to the site.
3. Keep the old repo. It is the only copy of the previous site, and its git history is the
   record of what was published before.

## What the workflow assumes

- `mockups/out` is the whole deployable site. It contains `index.html`, which `build.py`
  writes as a copy of `HOMEPAGE` (currently `a2-signal.html`).
- Everything the build reads is committed: `src/`, `data/`, `assets/`. The `tools/` scripts
  that generate assets from lab recordings are **not** run in CI — they need the lab server
  and are run by hand when the underlying data changes.
- The build is deterministic and takes a few seconds.

## Before the first real deploy

The pages are currently one self-contained file each, with fonts, clips and data inlined as
base64. That is right for emailing a mockup and wrong for a real site: the homepage is about
2.6 MB and none of it is cached between pages. Switching `build.py` to write linked assets
into `out/assets/` would cut the homepage to a few hundred KB and let the shared fonts and
recordings be fetched once. That change is worth making before launch, not after.
