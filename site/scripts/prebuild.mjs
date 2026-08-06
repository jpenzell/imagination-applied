// Stages publication artifacts from the canonical, manifest-verified package
// into the Astro site.
//
// The package under /publications/adoption-without-confidence/ is a verbatim
// copy of Adoption_Without_Confidence_2026_Open_Publication_Release_v3.1.0 and
// must stay byte-identical so `shasum -a 256 -c MANIFEST.sha256` keeps passing.
// Nothing in this script writes back into it. We copy out, never in.

import { cp, mkdir, readFile, writeFile, rm } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const siteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = path.resolve(siteRoot, '..');
const pkg = path.join(repoRoot, 'publications', 'adoption-without-confidence');

const SLUG = 'adoption-without-confidence';
const publicDir = path.join(siteRoot, 'public', 'publications', SLUG);
const contentDir = path.join(siteRoot, 'src', 'content');

// Friendly download URLs -> the real filenames inside the package. The package
// keeps its own names (the manifest hashes those paths); readers get these.
const DOWNLOADS = {
  'paper.pdf': 'publication/The_Developers_Using_AI_Without_Trusting_It_2026.pdf',
  'paper.docx': 'publication/The_Developers_Using_AI_Without_Trusting_It_2026.docx',
  'paper.html': 'publication/The_Developers_Using_AI_Without_Trusting_It_2026.html',
  'open-research-note.pdf': 'outputs/Adoption_Without_Confidence_Open_Research_Note_2026.pdf',
  'open-research-note.docx': 'outputs/Adoption_Without_Confidence_Open_Research_Note_2026.docx',
  'research-report.pdf': 'outputs/Adoption_Without_Confidence_Research_Report_2026.pdf',
  'research-report.docx': 'outputs/Adoption_Without_Confidence_Research_Report_2026.docx',
  'executive-brief.pdf': 'outputs/Favorable_Stance_Is_Not_Accuracy_Trust_Executive_Brief_2026.pdf',
  'executive-brief.docx': 'outputs/Favorable_Stance_Is_Not_Accuracy_Trust_Executive_Brief_2026.docx',
  'carousel.pdf': 'outputs/Favorable_Stance_Is_Not_Accuracy_Trust_LinkedIn_Carousel_2026.pdf',
  'CITATION.cff': 'CITATION.cff',
  'MANIFEST.sha256': 'MANIFEST.sha256',
};

async function main() {
  if (!existsSync(pkg)) {
    throw new Error(`Canonical package missing at ${pkg}`);
  }

  await rm(publicDir, { recursive: true, force: true });
  await mkdir(publicDir, { recursive: true });
  await mkdir(contentDir, { recursive: true });

  for (const [dest, src] of Object.entries(DOWNLOADS)) {
    const from = path.join(pkg, src);
    if (!existsSync(from)) throw new Error(`Missing package file: ${src}`);
    await cp(from, path.join(publicDir, dest));
  }

  // Figures, referenced relatively by the blog markdown.
  await cp(path.join(pkg, 'publication', 'assets'), path.join(publicDir, 'assets'), {
    recursive: true,
  });

  // The article body. Copied out and rewritten only where the rendering
  // context demands it: image paths become absolute, and the duplicated H1 +
  // italic subtitle are dropped because the page template renders both from
  // frontmatter. No wording is altered -- the language in this package went
  // through three review rounds and RELEASE_NOTES.md carries a binding
  // "Language to avoid" list.
  const raw = await readFile(path.join(pkg, 'publication', 'BLOG_POST.md'), 'utf8');
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
  if (!match) throw new Error('BLOG_POST.md: could not parse frontmatter');

  const [, frontmatter, bodyRaw] = match;

  let body = bodyRaw.replaceAll('](assets/', `](/publications/${SLUG}/assets/`);

  const beforeH1 = body;
  body = body.replace(/^\s*# The Developers Using AI Without Trusting It\r?\n/m, '');
  if (body === beforeH1) throw new Error('Expected H1 not found -- refusing to guess');

  const beforeSub = body;
  body = body.replace(
    /^\s*\*What 26,102 current users in Stack Overflow's 2025 survey reveal about adoption, sentiment, and calibrated skepticism\*\r?\n/m,
    ''
  );
  if (body === beforeSub) throw new Error('Expected subtitle line not found -- refusing to guess');

  await writeFile(
    path.join(contentDir, `${SLUG}.md`),
    `---\n${frontmatter}\n---\n${body.trimStart()}`,
    'utf8'
  );

  console.log(`prebuild: staged ${Object.keys(DOWNLOADS).length} downloads + figures + article`);
}

await main();
