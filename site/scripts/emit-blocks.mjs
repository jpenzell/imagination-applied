/**
 * Emits the joshpenzell.com registry file from site/src/lib/blocks.ts.
 *
 * Run: npm run emit:blocks
 * Then copy the printed file into the joshpenzell.com repo at
 *   shared/imagination-applied-blocks.ts
 * and add two lines to shared/site-content-registry.ts:
 *
 *   import { IMAGINATION_APPLIED_BLOCKS } from "./imagination-applied-blocks";
 *   ...and inside SITE_CONTENT_BLOCKS: ...IMAGINATION_APPLIED_BLOCKS,
 *
 * Generating rather than hand-maintaining is the point: the admin's defaults
 * and this site's fallbacks come from one source, so a block cannot exist in
 * one place and not the other, and cannot carry two different defaults.
 */

import { writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const siteRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// Node strips TypeScript types natively (>= 22.6 with the flag, >= 23 by
// default), so the source of truth can be imported as-is with no build step.
const { BLOCKS } = await import(path.join(siteRoot, 'src/lib/blocks.ts'));

const header = `// GENERATED FILE — do not edit by hand.
//
// Source: imagination-applied repo, site/src/lib/blocks.ts
// Regenerate with: npm run emit:blocks   (in that repo)
//
// These blocks are the editable surface of imaginationapplied.ai. They appear
// in the Site Content admin tab like any other block. Publishing one fires the
// Cloudflare deploy hook, which rebuilds that site with the new copy.
//
// The \`ia.*\` namespace keeps them from colliding with joshpenzell.com's own
// blocks in the shared site_content table.

import type { SiteContentBlockDef } from "./site-content-registry";

export const IMAGINATION_APPLIED_BLOCKS: SiteContentBlockDef[] = ${JSON.stringify(
  BLOCKS,
  null,
  2
)};
`;

const outDir = path.join(siteRoot, '..', 'integration');
await mkdir(outDir, { recursive: true });
const out = path.join(outDir, 'imagination-applied-blocks.ts');
await writeFile(out, header, 'utf8');
console.log(`emit:blocks — ${BLOCKS.length} blocks -> ${path.relative(process.cwd(), out)}`);
