import { DOORS } from '../consts.ts';
/**
 * The editable surface of imaginationapplied.ai.
 *
 * This is the single definition of every block Josh can edit from the Site
 * Content tab of the joshpenzell.com admin. It is deliberately ONE file used
 * by BOTH sides:
 *
 *   • This site reads `defaultValue` as the compiled-in fallback, so the page
 *     is always complete even with no database and no network.
 *   • `npm run emit:blocks` turns this same list into the registry file that
 *     joshpenzell.com imports, so the admin shows exactly these blocks with
 *     exactly these defaults.
 *
 * Two definitions of the same content is how the copy on a site drifts from
 * the copy in its CMS. There is only one here.
 *
 * Block ids are namespaced `ia.*` so they cannot collide with joshpenzell.com's
 * own blocks in the shared `site_content` table.
 *
 * Every default must be real, shippable copy. If a default is a placeholder,
 * a fetch failure ships the placeholder.
 */

export interface BlockDef {
  blockId: string;
  /** Mirrors joshpenzell.com's SiteContentBlockType. */
  type: 'text' | 'richtext' | 'seo' | 'list';
  /** Grouping label in the admin, e.g. "Imagination Applied — Home". */
  page: string;
  label: string;
  defaultValue: unknown;
  itemFields?: { key: string; label: string; type: string; optional?: boolean }[];
  itemTitleKey?: string;
}

const IA = 'Imagination Applied';

export const BLOCKS: BlockDef[] = [
  // ---- per-page SEO -------------------------------------------------
  // The reason this site exists is that these values must be correct in the
  // raw HTML. Exposing them to the admin means Josh can fix a title without
  // a developer, and the fix still lands in the static bytes.
  {
    blockId: 'ia.seo.home.artistic-intelligence.v2',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'Home page SEO',
    defaultValue: {
      title: 'Imagination Applied | AI Work Rehearsals for Teams',
      description:
        'Imagination Applied helps leaders and teams rehearse consequential AI work before the consequences are real.',
    },
  },
  {
    blockId: 'ia.seo.how-we-work.v2',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'How we work SEO',
    defaultValue: {
      title: 'How we work',
      description:
        'TheaterThink is our rehearsal-based practice: direct the work, cast the ensemble, rehearse before the stakes are irreversible. Direct, Cast, Rehearse, Interpret.',
    },
  },
  {
    blockId: 'ia.seo.keynotes.v2',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'Keynotes and workshops SEO',
    defaultValue: {
      title: 'Keynotes and workshops',
      description:
        'Josh-led keynotes and rehearsal-based workshops on Artistic Intelligence, creativity, leadership, and the age of AI.',
    },
  },
  {
    blockId: 'ia.seo.advisory.v2',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'Executive advisory SEO',
    defaultValue: {
      title: 'Transformation Advisory',
      description:
        'For leaders making consequential choices about direction, capability, work design, AI, and organizational change.',
    },
  },
  {
    blockId: 'ia.seo.consulting.v2',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'Transformation consulting SEO',
    defaultValue: {
      title: 'The Rehearsal Room',
      description:
        'Build working proof, learn through bounded experiments, and transfer the practice until your team can run it without us.',
    },
  },
  {
    blockId: 'ia.seo.about.v2',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'About SEO',
    defaultValue: {
      title: 'About',
      description:
        'Imagination Applied is the company that brings Artistic Intelligence into organizations through AI work rehearsals, keynotes and Transformation Advisory.',
    },
  },
  {
    blockId: 'ia.seo.publications',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'Research index SEO',
    defaultValue: {
      title: 'Research',
      description:
        'Open research from Imagination Applied, with traceable claims, stated limitations, reproducible analysis, and released checksums.',
    },
  },
  {
    blockId: 'ia.seo.contact.v2',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'Contact SEO',
    defaultValue: {
      title: 'Contact',
      description:
        'Tell us what the work is actually about. Imagination Applied works with leaders and teams on AI work rehearsals, ongoing practice, keynotes and advisory.',
    },
  },

  // ---- home ---------------------------------------------------------
  {
    blockId: 'ia.home.hero.headline.v2',
    type: 'text',
    page: `${IA} — Home`,
    label: 'Hero headline (the final word renders in orange)',
    defaultValue: 'Do not roll out the future. Rehearse it.',
  },
  {
    blockId: 'ia.home.hero.lede.v2',
    type: 'text',
    page: `${IA} — Home`,
    label: 'Hero supporting line',
    defaultValue:
      'Bring one consequential workflow and the people who own it. We help your team direct AI, test human judgment and decide what to pilot, revise or stop.',
  },
  {
    blockId: 'ia.home.tension.heading',
    type: 'text',
    page: `${IA} — Home`,
    label: 'Tension section heading',
    defaultValue: 'Possibility is abundant. Direction is not.',
  },
  {
    blockId: 'ia.home.tension.body',
    type: 'richtext',
    page: `${IA} — Home`,
    label: 'Tension section body (HTML)',
    defaultValue:
      '<p>Organizations are surrounded by possibility and starved for direction. They can generate more options, more content, and more analysis than ever. But output does not produce shared meaning, good judgment, or movement.</p>' +
      '<p>This is true in innovation, learning, strategy, culture, and change. AI accelerates it: a model can produce a beautiful answer to a question nobody meant to ask.</p>' +
      '<p>The decision—what is worth making—lives in interpretation. In the point of view you bring, the ensemble you compose, and what you learn when the idea finally has to move.</p>',
  },
  {
    blockId: 'ia.home.research.blurb',
    type: 'text',
    page: `${IA} — Home`,
    label: 'Research section blurb',
    defaultValue:
      'Advice about AI adoption is cheap. We test ours, publish the code and the checksums, and state the limitations in the body of the work rather than in a footnote.',
  },

  // ---- the ways to work together -----------------------------------
  {
    blockId: 'ia.doors.items.v2',
    type: 'list',
    page: `${IA} — Ways to work together`,
    label: 'The four ways to work together',
    itemTitleKey: 'title',
    itemFields: [
      { key: 'title', label: 'Title', type: 'text' },
      { key: 'href', label: 'Page path', type: 'url' },
      { key: 'for', label: 'Who it is for', type: 'textarea' },
      { key: 'outcome', label: 'Outcome', type: 'textarea' },
    ],
    defaultValue: DOORS,
  },

  // ---- global -------------------------------------------------------
  {
    blockId: 'ia.global.description.v2',
    type: 'text',
    page: `${IA} — Global`,
    label: 'Company description (footer, meta, JSON-LD)',
    defaultValue:
      'Imagination Applied helps leaders and teams rehearse consequential AI work before the consequences are real.',
  },
  {
    blockId: 'ia.global.contactEmail',
    type: 'text',
    page: `${IA} — Global`,
    label: 'Contact email address',
    defaultValue: 'josh@imaginationapplied.ai',
  },
];

/** Lookup for defaults, so callers never restate copy. */
export const DEFAULTS: Record<string, unknown> = Object.fromEntries(
  BLOCKS.map((b) => [b.blockId, b.defaultValue])
);

export function defaultText(blockId: string): string {
  const v = DEFAULTS[blockId];
  if (typeof v !== 'string') {
    throw new Error(`blocks.ts: ${blockId} is not a text block`);
  }
  return v;
}

export function defaultSeo(blockId: string): { title: string; description: string; ogImage?: string } {
  const v = DEFAULTS[blockId] as { title: string; description: string; ogImage?: string } | undefined;
  if (!v || typeof v !== 'object' || !v.title || !v.description) {
    throw new Error(`blocks.ts: ${blockId} is not a complete seo block`);
  }
  return v;
}
