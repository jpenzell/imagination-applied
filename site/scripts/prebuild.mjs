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
const currentPkg = path.join(repoRoot, 'publications', 'adoption-without-confidence-2026');

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
  'MANIFEST.sha256': 'MANIFEST.sha256',
};

// Current and archived citations are kept separately from the frozen package.
// The current citation has no DOI until a distinct 2026 record is assigned.
const ROOT_CITATION = path.join(repoRoot, 'CITATION.cff');

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

  if (!existsSync(ROOT_CITATION)) throw new Error('Missing root CITATION.cff');
  await cp(ROOT_CITATION, path.join(publicDir, 'CITATION.cff'));
  await cp(path.join(repoRoot, 'CITATION-2025.cff'), path.join(publicDir, 'CITATION-2025.cff'));

  const currentDownloads = {
    'executive-brief-2026.pdf': 'executive-brief.pdf',
    'executive-brief-2026.docx': 'executive-brief.docx',
    'carousel-2026.pdf': 'carousel.pdf',
    'daily-use-by-attitude-2026.png': 'daily-use-by-attitude-2026.png',
    'MANIFEST-2026.sha256': 'MANIFEST.sha256',
  };
  for (const [dest, src] of Object.entries(currentDownloads)) {
    await cp(path.join(currentPkg, src), path.join(publicDir, dest));
  }

  // Figures, referenced relatively by the blog markdown.
  await cp(path.join(pkg, 'publication', 'assets'), path.join(publicDir, 'assets'), {
    recursive: true,
  });

  // Render the new brief on the current page. The old article HTML and all old
  // download URLs remain byte-identical archive assets staged above.
  const raw = await readFile(path.join(currentPkg, 'executive-brief.md'), 'utf8');
  const lines = raw.split(/\r?\n/);
  const byline = lines.findIndex((line) => line.startsWith('Josh Penzell |'));
  if (byline < 0) throw new Error('2026 brief: expected byline not found');
  const body = lines.slice(byline + 1).join('\n')
    .replaceAll('](daily-use-by-attitude-2026.png)', `](/publications/${SLUG}/daily-use-by-attitude-2026.png)`)
    .replaceAll('https://github.com/jpenzell/ai-adoption-paradox', 'https://github.com/jpenzell/ai-adoption-paradox/tree/v3.2.0');
  await writeFile(path.join(contentDir, `${SLUG}.md`), body.trimStart(), 'utf8');

  console.log(`prebuild: staged ${Object.keys(DOWNLOADS).length} historical downloads + 2026 assets + article`);
}

await main();
