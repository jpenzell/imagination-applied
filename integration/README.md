# Connecting this site to the joshpenzell.com admin

One admin, one database, one leads system. This folder holds the pieces that
join the two.

## How it fits together

```
joshpenzell.com  (Replit · Express · Neon)      imaginationapplied.ai  (Astro · Cloudflare Pages)
│
├─ admin ▸ Site Content tab
│    16 "ia.*" blocks ───────────────────────▸  read at BUILD time
│    draft ▸ publish                             GET /api/site-content  (public, already existed)
│                                                fallback: compiled-in defaults
│
├─ publish fires the deploy hook ────────────▸  Cloudflare rebuilds
│
└─ leads + HubSpot  ◂──────────────────────────  contact form
     POST /api/partner/leads                     Pages Function, shared secret
     recordLeadTouch + syncLeadToHubSpot
```

## Why content is pulled at build time, not in the browser

This is the one design decision worth understanding before changing anything.

The site is static so every page ships its real `<title>`, `<meta description>`,
`<link rel=canonical>` and `og:` tags in the raw HTML. That is the entire reason
it is not part of the existing SPA: a client-rendered page sets metadata only
after JavaScript runs, so LinkedIn, Slack and X read the raw bytes and unfurl
**every** URL as the homepage card.

Fetching copy in the browser would reintroduce exactly that bug. So the content
is fetched once during `astro build` and baked into HTML.

The trade: a publish takes about a minute to appear rather than being instant.
In exchange, every page keeps correct metadata in its raw bytes, and the site
stays up and correct even when the Replit is asleep or mid-deploy.

## Status

Wired and verified 2026-08-12:

| | |
|---|---|
| Cloudflare Pages project | live at `imagination-applied.pages.dev` |
| Deploy hook `site-content-publish` | created, branch `main` |
| Cloudflare `PARTNER_SECRET` | set as an encrypted Secret |
| Cloudflare `CONTACT_FALLBACK` | set |
| Replit `IA_PARTNER_SECRET` / `IA_DEPLOY_HOOK_URL` | set |
| Branch merged into the Repl | merge commit, no conflicts, `tsc --noEmit` clean |
| `POST /api/partner/leads` | live, returns 401 to unauthenticated calls |

Remaining: DNS (see `dns-migration.md`) and the Zenodo DOI.

⚠️ The Repl is the source of truth and was **16 commits ahead of GitHub** when
this was merged. Merge integration branches *inside Replit* — merging them on
GitHub does not reach the running app and risks being overwritten on the next
Replit push.

## Setup

### 1. joshpenzell.com — merge the branch

Branch: `imagination-applied-integration` on `jpenzell/JoshPenzell`.
Additive only: 387 insertions, 0 deletions, `tsc --noEmit` clean.

It adds the 16 blocks to the Site Content registry, fires a deploy hook from
`invalidateSiteContentCache()`, and adds `POST /api/partner/leads`.

Without the two env vars below, merging is inert: the blocks show up in the
admin and nothing else activates.

### 2. Cloudflare Pages — create a deploy hook

Pages project ▸ Settings ▸ Builds & deployments ▸ Deploy hooks ▸ Add.
Name it `site-content-publish`, branch `main`. Copy the URL it gives you.

### 3. Set four environment variables

Generate one shared secret and use the same value on both sides:

```bash
openssl rand -hex 32
```

**On joshpenzell.com** (Replit ▸ Secrets):

| Name | Value |
|---|---|
| `IA_DEPLOY_HOOK_URL` | the deploy-hook URL from step 2 |
| `IA_PARTNER_SECRET` | the generated secret |

**On Cloudflare Pages** (Settings ▸ Environment variables):

| Name | Value |
|---|---|
| `PARTNER_SECRET` | the same generated secret |
| `CONTACT_FALLBACK` | an email address shown if delivery ever fails |

The secret must be at least 32 characters. `partner-leads.ts` fails closed:
if `IA_PARTNER_SECRET` is unset or too short, every request gets a 401. An
unset secret can never mean "allow everyone".

### 4. Check it end to end

- Edit `ia.home.hero.lede` in the admin, publish, wait ~1 minute, reload the
  home page. Cloudflare ▸ Deployments should show a build triggered by a hook.
- Submit the contact form. The enquiry should appear in the admin's leads with
  source `imagination_applied`.

## Editing the blocks

`site/src/lib/blocks.ts` in this repo is the single definition. It is both the
compiled-in fallback **and** the source for the admin registry, so the two
cannot drift or carry different defaults.

To add or change a block:

```bash
cd site && npm run emit:blocks
```

Then copy `integration/imagination-applied-blocks.ts` into the joshpenzell.com
repo at `shared/imagination-applied-blocks.ts` and deploy.

Block ids are namespaced `ia.*` so they cannot collide with joshpenzell.com's
own blocks in the shared `site_content` table.

## Failure behaviour

Everything degrades rather than breaks:

| If this fails | Then |
|---|---|
| joshpenzell.com is down at build time | Build succeeds with compiled-in defaults; a warning is logged. Copy is not fresh; nothing is blank or broken. |
| The deploy hook fails | The publish still succeeds. This site shows the previous copy until the next publish or a manual redeploy. |
| The leads endpoint is down | The sender sees a readable page with a fallback email address, not a crash. |
| The rate limiter trips | The sender is told plainly to try again shortly. |

To build with no network at all:

```bash
CONTENT_API_DISABLED=true npm run build
```
