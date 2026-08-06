# Imagination Applied

Source for [imaginationapplied.ai](https://imaginationapplied.ai) and for the research
published under the Open Research Series.

One repository holds both, deliberately: when a page says "here is the source," that
should be literally true.

```
site/                                    Astro site (static, zero client JavaScript)
publications/adoption-without-confidence/  Reproducibility package, v3.1.0
```

## The research

`publications/adoption-without-confidence/` is a verbatim copy of the
`Adoption_Without_Confidence_2026_Open_Publication_Release_v3.1.0` package. It is not
edited here — not reformatted, not re-run, not "improved." Its integrity is checkable:

```bash
cd publications/adoption-without-confidence && shasum -a 256 -c MANIFEST.sha256
```

That must report 58 files OK. The build never writes into this directory;
`site/scripts/prebuild.mjs` copies artifacts out of it and stages them for the site.

**Stack Overflow survey data are not redistributed here.** The analysis code and the
file checksums are. `publications/adoption-without-confidence/data/README_data.md`
documents how to obtain the official CSVs and verify that what you downloaded matches
what was analyzed.

## The site

Astro, built as static HTML and deployed to Cloudflare Pages.

```bash
cd site
npm install
npm run dev      # http://localhost:4321
npm run build    # -> site/dist
```

### The one hard requirement

Every page ships its own `<title>`, `<meta name="description">`, `<link rel="canonical">`
and Open Graph tags **in the raw HTML, before any JavaScript runs**. Social platforms and
chat apps read the raw bytes; a client-rendered page unfurls every URL as its homepage.
That failure is the reason this site is static.

`src/layouts/Base.astro` is the only place head metadata is produced, and it throws at
build time if a page omits a title or description — there is no silent site-wide
fallback on purpose.

To verify against a deployment:

```bash
for p in / /about/ /publications/adoption-without-confidence/; do
  curl -s "https://imaginationapplied.ai$p" | grep -i -e '<title' -e 'og:title' -e canonical
done
```

Three different, correct results. Not three copies of the homepage.

### Contact form

`site/functions/api/contact.ts` is a Cloudflare Pages Function — the only dynamic
endpoint. It needs three environment variables set in the Cloudflare Pages dashboard
(never in this repo): `RESEND_API_KEY`, `CONTACT_TO`, `CONTACT_FROM`.

Site copy follows the Imagination Applied Brand Guide (v1.0, July 2026), which is
authoritative over older website copy. Language in the publication follows that
package's own `RELEASE_NOTES.md`, including its binding "Language to avoid" list.

## Licence

Analysis code and publication assets: MIT, per
`publications/adoption-without-confidence/LICENSE`.
