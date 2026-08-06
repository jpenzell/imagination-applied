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
    blockId: 'ia.seo.home',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'Home page SEO',
    defaultValue: {
      title: 'Imagination Applied',
      description:
        'Imagination Applied helps leaders and teams turn uncertainty into direction through keynotes, advisory work, and rehearsal-based transformation.',
    },
  },
  {
    blockId: 'ia.seo.how-we-work',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'How we work SEO',
    defaultValue: {
      title: 'How we work',
      description:
        'TheaterThink is our rehearsal-based practice: direct the work, cast the ensemble, rehearse before the stakes are irreversible. Three moves, in order.',
    },
  },
  {
    blockId: 'ia.seo.keynotes',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'Keynotes and workshops SEO',
    defaultValue: {
      title: 'Keynotes and workshops',
      description:
        'For conferences, leadership meetings, offsites, and learning events that need a shared language and a memorable experience.',
    },
  },
  {
    blockId: 'ia.seo.advisory',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'Executive advisory SEO',
    defaultValue: {
      title: 'Executive advisory',
      description:
        'For leaders making consequential choices about AI, adoption, capability, work design, and organizational direction.',
    },
  },
  {
    blockId: 'ia.seo.consulting',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'Transformation consulting SEO',
    defaultValue: {
      title: 'Transformation consulting',
      description:
        'For organizations ready to move from inspiration to changes in behavior, workflow, learning, or operating practice.',
    },
  },
  {
    blockId: 'ia.seo.about',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'About SEO',
    defaultValue: {
      title: 'About',
      description:
        'Imagination Applied brings Artistic Intelligence into organizations through live experiences, executive advisory, and rehearsal-based transformation. Founded by Josh Penzell.',
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
        'Open research from Imagination Applied. Every claim traceable to code, limitations stated in the body rather than a footnote, and the analysis released with its checksums.',
    },
  },
  {
    blockId: 'ia.seo.contact',
    type: 'seo',
    page: `${IA} — SEO`,
    label: 'Contact SEO',
    defaultValue: {
      title: 'Contact',
      description:
        'Tell us what the work is actually about. Imagination Applied works with leaders and teams on AI adoption, advisory, and rehearsal-based transformation.',
    },
  },

  // ---- home ---------------------------------------------------------
  {
    blockId: 'ia.home.hero.headline',
    type: 'text',
    page: `${IA} — Home`,
    label: 'Hero headline (the final word renders in orange)',
    defaultValue: 'Don’t Just Prompt. Direct.',
  },
  {
    blockId: 'ia.home.hero.lede',
    type: 'text',
    page: `${IA} — Home`,
    label: 'Hero supporting line',
    defaultValue:
      'AI can make almost anything. The real leadership challenge is deciding what is worth making—and creating the conditions to make it real.',
  },
  {
    blockId: 'ia.home.tension.heading',
    type: 'text',
    page: `${IA} — Home`,
    label: 'Tension section heading',
    defaultValue: 'The problem is not capability. It is direction.',
  },
  {
    blockId: 'ia.home.tension.body',
    type: 'richtext',
    page: `${IA} — Home`,
    label: 'Tension section body (HTML)',
    defaultValue:
      '<p>Organizations are surrounded by possibility and starved for direction. They can generate more options, more content, more analysis than ever. But more output does not produce shared meaning, good judgment, or movement.</p>' +
      '<p>Teams can be competent and still be in different plays. Leaders can move quickly and still move in the wrong direction. AI can produce a beautiful answer to a question nobody meant to ask.</p>' +
      '<p>That decision—what is worth making—is not hidden inside a better prompt. It lives in interpretation. In the point of view you bring, the people and tools you put in the room, and what you learn when the idea finally has to move.</p>',
  },
  {
    blockId: 'ia.home.research.blurb',
    type: 'text',
    page: `${IA} — Home`,
    label: 'Research section blurb',
    defaultValue:
      'Advice about AI adoption is cheap. We test ours, publish the code and the checksums, and state the limitations in the body of the work rather than in a footnote.',
  },

  // ---- the three doors ----------------------------------------------
  // Titles and Outcome lines are verbatim from the Brand Guide, section 7.
  {
    blockId: 'ia.doors.items',
    type: 'list',
    page: `${IA} — Ways to work together`,
    label: 'The three doors',
    itemTitleKey: 'title',
    itemFields: [
      { key: 'title', label: 'Title', type: 'text' },
      { key: 'href', label: 'Page path', type: 'url' },
      { key: 'for', label: 'Who it is for', type: 'textarea' },
      { key: 'outcome', label: 'Outcome', type: 'textarea' },
    ],
    defaultValue: [
      {
        title: 'Keynotes and Workshops',
        href: '/keynotes-and-workshops/',
        for: 'For conferences, leadership meetings, offsites, and learning events that need a shared language and a memorable experience.',
        outcome: 'A room sees the challenge differently and leaves with a move it can use.',
      },
      {
        title: 'Executive Advisory',
        href: '/executive-advisory/',
        for: 'For leaders making consequential choices about AI, adoption, capability, work design, and organizational direction.',
        outcome: 'Clearer interpretation, better decisions, and a rehearsal plan for what comes next.',
      },
      {
        title: 'Transformation Consulting',
        href: '/transformation-consulting/',
        for: 'For organizations ready to move from inspiration to changes in behavior, workflow, learning, or operating practice.',
        outcome: 'A series of bounded experiments that create evidence, trust, and scalable direction.',
      },
    ],
  },

  // ---- global -------------------------------------------------------
  {
    blockId: 'ia.global.description',
    type: 'text',
    page: `${IA} — Global`,
    label: 'Company description (footer, meta, JSON-LD)',
    defaultValue:
      'Imagination Applied helps leaders and teams turn uncertainty into direction through keynotes, advisory work, and rehearsal-based transformation.',
  },
  {
    blockId: 'ia.global.contactEmail',
    type: 'text',
    page: `${IA} — Global`,
    label: 'Contact email address',
    defaultValue: 'hello@imaginationapplied.ai',
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
