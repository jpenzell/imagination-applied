# Conflicts register — what is stale, where it lives, what is right

**Audited 2026-08-12** against `Josh_Penzell_Imagination_Applied_Brand_Guide_2026.docx`
(v1.0, July 2026), which states it should be used "ahead of older website copy,
legacy TheaterThink materials, earlier talk catalogs, and framework lists that
conflict with it."

Every finding below is **evidence, not inference** — each one was read out of
the live `GET /api/site-content` payload or off disk, and the block id is given
so it can be fixed at source.

---

## The actual problem

There is no single place that is *supposed* to be right.

Positioning lives in a docx in `~/Downloads`. Site copy lives in a Postgres
table. The book catalogue lives in ~40 near-identical dated ZIPs. Claims live in
whichever bio was written last. Nothing reconciles them, so nothing is ever
wrong enough to fix — it just gets superseded by another file.

**Symptom, not cause:** an hour before writing this, the catalogue page on
imaginationapplied.ai listed 6 books. The Press has 13. The page was built from
the first package found in Downloads, because there was nothing to check it
against.

---

## A. Live on joshpenzell.com — published content blocks

18 blocks are published (the rest of the site runs on registry defaults).

### A1 — "Director of the Digital Age" · 4 blocks · **highest priority**

| Block | |
|---|---|
| `presskit.bio.short` | legacy tagline |
| `presskit.bio.medium` | legacy tagline |
| `presskit.bio.long` | legacy tagline |
| `site.footer.bio` | legacy tagline |

The Guide never uses this line. Its primary public identity is **"Keynote
Speaker, Advisor, and Author"**, with the supporting descriptor "a theater
director turned AI strategist helping leaders rehearse what comes next."

This matters more than the others because these are the **press-kit bios** —
the text other people copy into event programmes and introductions. A stale
bio propagates into rooms you are not in.

**The replacement already exists.** The Guide, section 12, "Standard Bios":

> **25 words** — Josh Penzell is a keynote speaker, advisor, and forthcoming author helping leaders direct AI, align people, and rehearse what comes next.

> **50 words** — Josh Penzell is a keynote speaker, advisor, and founder of Imagination Applied. A theater director turned AI strategist, he helps leaders create direction when the answer is not waiting to be found—aligning people, directing AI, and rehearsing what comes next.

The 100- and 200-word versions are in the same section, along with a standard
emcee introduction.

### A2 — "Human Caffeine" · `frameworks.frameworks.items`

The Guide: *"Do not currently lead the brand or main talk menu with it… It
should not currently sit beside Artistic Intelligence and TheaterThink as an
equal public pillar."* It is listed as a framework alongside them.

Keep the concept; demote the placement.

### A3 — Claims that need permission before they appear in evergreen copy

Present in live blocks: **Zillow ×2**, **Special Olympics ×2**, **"200+" ×2**.

The Guide's Proof Bank is explicit: *"Verify the exact role, date, client
permission, and wording before adding Zillow, Zoox, Special Olympics, Microsoft,
client outcomes, stage counts, audience totals, or revenue claims to evergreen
copy."*

Not necessarily wrong — but each needs a recorded permission, and none has one.
This is the finding most likely to cause a real problem, because a client
noticing their name used without permission is a relationship, not a typo.

### A4 — The flagship keynote is missing

**"Rehearsing the Future"** — the Guide's canonical flagship title — appears in
**zero** published blocks. "AI at the Speed of Live" appears once.

### A5 — "Moment" · `home.socialproof.testimonials`

The Guide's Four M's are **Metaphor, Mechanics, Motion, Meaning**. The January
content framework used **Mechanisms** and **Moment**. Only a trace survives in
live copy, but the Guide's cleanup rules say "Correct the Four M's everywhere."

---

## B. Documents that contradict the Guide

| File | Conflict |
|---|---|
| `~/Downloads/Artistic Intelligence _ 2026 Content Strategy.docx` (Jan 28) | Four M's as *Mechanisms/Moment*; leads with Human Caffeine; introduces "AQ" and a sensory model absent from the Guide |
| `~/JoshPenzell/CROSS_SITE_LINKING_STRATEGY.md` | Built entirely around thesixmindsets.com as a co-equal brand, which the Guide demotes to supporting IP |

Neither is wrong to have existed. Both are older than the Guide and neither is
marked as superseded, so either could be picked up and followed by mistake.

---

## C. The catalogue — 13 books with no public record

Three series, all under the **Imagination Applied Press** imprint (already the
imprint of record in the KDP submission cards):

- **The Forgotten Playbook Library** — 6 titles, production-complete
- **The Past Tests You** — 4 titles, publish-ready packages
- **Stories That Rehearsed Tomorrow** — 3 titles, **Kindle US-only ready; paperback held** pending Canadian rights review

Until 2026-08-12 none of this existed anywhere public. It now lives in
`site/src/press.ts` as a registry with a status per title.

---

## D. Where imaginationapplied.ai stands

Checked against the same list: **clean**. No legacy tagline, no Mechanisms/Moment,
no Human Caffeine, no unverified client claims. It was built to the Guide, and
the Guide's Proof Bank is why the About page lists ELB Learning, Amazon Alexa,
Skillsoft, Brooklyn College, Northwestern and TD Magazine — and not Zillow.

---

## The fix, in order

1. **Replace the four bios** with the Guide's standard bios. Highest leverage:
   it is the copy other people reproduce.
   ⚠️ These are `text` blocks, which the admin **cannot currently edit** — that is
   what branch `ia-text-block-editor` on `jpenzell/JoshPenzell` unblocks. Merge
   it first (`git fetch origin && git merge origin/ia-text-block-editor` in the
   Replit Shell) and this becomes a five-minute job.
2. **Record permission, or remove the name** for Zillow, Special Olympics and
   the 200+ figure.
3. **Mark the two stale documents superseded** — a header line pointing at the
   Guide costs nothing and stops them being followed by accident.
4. **Add "Rehearsing the Future"** to the published talk portfolio.
5. **Decide whether the Guide still holds.** It predates a 13-book publishing
   operation and describes a company that sells keynotes, advisory and
   consulting. That is no longer the whole company.

## Keeping it fixed

The pattern that already works in this repo: **one definition, generated
outward.** `site/src/lib/blocks.ts` is both the site's fallback copy and the
source of the admin's registry, so the two cannot disagree. `site/src/press.ts`
now does the same for the catalogue.

The same shape would work for the Guide itself — positioning, the proof bank
with its permission status, and the canonical framework names as one versioned
file both sites read. Then "is this claim approved?" has an answer that can be
looked up rather than remembered.
