/**
 * Content bridge to the joshpenzell.com admin.
 *
 * Copy on this site is editable from the Site Content tab of the existing
 * admin at joshpenzell.com. There is one admin, one database, one publish
 * button — this file is the other end of that wire.
 *
 * ── Why this runs at BUILD time and never in the browser ──────────────────
 *
 * The whole reason this site is not the existing SPA is that a client-rendered
 * page ships raw HTML without real per-page metadata, so LinkedIn and Slack
 * unfurl every URL as the homepage card. Fetching copy in the browser would
 * reintroduce exactly that failure: the title and description a crawler reads
 * would be whatever was compiled in, not what the admin says.
 *
 * So content is pulled once, during `astro build`, and baked into static HTML.
 * A publish in the admin fires a Cloudflare deploy hook, which rebuilds. The
 * round trip is a minute rather than instant, and in exchange every page keeps
 * correct metadata in its raw bytes and stays up even when the Replit is
 * asleep.
 *
 * ── Failure behaviour ────────────────────────────────────────────────────
 *
 * Never fail the build on a content fetch. joshpenzell.com being slow, asleep,
 * or mid-deploy must not take down this site or blank its copy. Every value
 * has a compiled-in default; the network is an enhancement. A failed fetch is
 * loud in the build log and invisible on the page.
 */

/** Shape returned by GET /api/site-content (public, live values only). */
interface SiteContentBlock {
  blockId: string;
  blockType: 'text' | 'richtext' | 'image' | 'file' | 'list' | 'seo' | 'json';
  liveValue: unknown;
}

export interface SeoValue {
  title?: string;
  description?: string;
  keywords?: string;
  ogImage?: string;
}

// Read from both: Vite injects import.meta.env, while a Cloudflare Pages build
// sets dashboard variables as process.env. Checking only one would make an
// override set in the dashboard silently do nothing.
function env(name: string): string | undefined {
  const viteVal = (import.meta.env as Record<string, string | undefined>)[name];
  if (viteVal) return viteVal;
  return typeof process !== 'undefined' ? process.env?.[name] : undefined;
}

const ENDPOINT = env('CONTENT_API_URL') ?? 'https://joshpenzell.com/api/site-content';
const TIMEOUT_MS = 8000;

let cache: Map<string, unknown> | null = null;
let stats = { fetched: 0, ok: false };

async function load(): Promise<Map<string, unknown>> {
  if (cache) return cache;
  cache = new Map();

  // Opt out entirely (offline work, CI without network) without editing code.
  if (env('CONTENT_API_DISABLED') === 'true') {
    console.log('[content] disabled by CONTENT_API_DISABLED — using defaults');
    return cache;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(ENDPOINT, {
      signal: controller.signal,
      headers: { accept: 'application/json' },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const blocks = (await res.json()) as SiteContentBlock[];
    if (!Array.isArray(blocks)) throw new Error('expected an array of blocks');

    for (const b of blocks) {
      // A published-but-emptied block should fall back rather than render a
      // blank page, so null/undefined/"" never enter the map.
      if (!b?.blockId) continue;
      if (b.liveValue === null || b.liveValue === undefined || b.liveValue === '') continue;
      cache.set(b.blockId, b.liveValue);
    }
    stats = { fetched: cache.size, ok: true };
    console.log(`[content] ${cache.size} live blocks from ${ENDPOINT}`);
  } catch (err) {
    const why = err instanceof Error ? err.message : String(err);
    console.warn(
      `[content] could not reach ${ENDPOINT} (${why}). ` +
        'Building with compiled-in defaults — the site is fine, the copy is just not fresh.'
    );
  } finally {
    clearTimeout(timer);
  }
  return cache;
}

/** Prime the cache once per build. Safe to call repeatedly. */
export async function initContent(): Promise<void> {
  await load();
}

export function contentStatus(): { fetched: number; ok: boolean } {
  return stats;
}

/**
 * A single line of text, or the fallback.
 * The fallback is the source of truth until someone edits the block, so it
 * must always be real, shippable copy — never a placeholder.
 */
export async function text(blockId: string, fallback: string): Promise<string> {
  const map = await load();
  const v = map.get(blockId);
  return typeof v === 'string' && v.trim() ? v : fallback;
}

/** An HTML fragment, or the fallback. Rendered with set:html by the caller. */
export async function richtext(blockId: string, fallback: string): Promise<string> {
  return text(blockId, fallback);
}

/**
 * Per-page SEO override. Any field the admin leaves blank keeps the
 * compiled-in value, so a half-filled block cannot strip a page's metadata.
 */
export async function seo(
  blockId: string,
  fallback: { title: string; description: string; ogImage?: string }
): Promise<{ title: string; description: string; ogImage?: string }> {
  const map = await load();
  const v = map.get(blockId) as SeoValue | undefined;
  if (!v || typeof v !== 'object') return fallback;
  return {
    title: typeof v.title === 'string' && v.title.trim() ? v.title : fallback.title,
    description:
      typeof v.description === 'string' && v.description.trim()
        ? v.description
        : fallback.description,
    ogImage:
      typeof v.ogImage === 'string' && v.ogImage.trim() ? v.ogImage : fallback.ogImage,
  };
}

/** A list block, or the fallback. Shape is validated by the caller. */
export async function list<T>(blockId: string, fallback: readonly T[]): Promise<readonly T[]> {
  const map = await load();
  const v = map.get(blockId);
  return Array.isArray(v) && v.length ? (v as T[]) : fallback;
}
