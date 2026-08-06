// Site-wide constants.
//
// Copy in this file is drawn from Josh_Penzell_Imagination_Applied_Brand_Guide_2026.docx
// (v1.0, July 2026), which the guide itself declares authoritative over older
// website copy. Where a line is quoted from the guide it is marked. Do not
// replace guide language with a paraphrase without updating the guide first.

export const SITE = {
  /** Legal/brand name. No trademark symbol -- guide, Naming and Trademark Rules. */
  name: 'Imagination Applied',
  origin: 'https://imaginationapplied.ai',

  /** Guide, section 3, "Recommended description". */
  description:
    'Imagination Applied helps leaders and teams turn uncertainty into direction through keynotes, advisory work, and rehearsal-based transformation.',

  /** Guide, section 12, "Company Boilerplate". */
  boilerplate:
    'Imagination Applied helps leaders and teams turn uncertainty into direction. Founded by keynote speaker, advisor, and theater director Josh Penzell, the company brings Artistic Intelligence into organizations through live experiences, executive advisory, and rehearsal-based transformation. Its practice, TheaterThink, helps people interpret what matters, compose the right ensemble, and learn by putting possibilities into motion—especially as AI changes how work gets made.',

  /** Guide, section 12, Website hero. Punctuation is canonical -- preserve it. */
  hero: 'Don’t Just Prompt. Direct.',

  /** Guide, section 3, "Optional internal line". */
  tagline: 'Artistic Intelligence, applied.',

  founder: 'Josh Penzell',
  founderSite: 'https://joshpenzell.com',
  linkedin: 'https://www.linkedin.com/company/imaginationapplied',

  /**
   * Where contact-form submissions are delivered, and the address shown on the
   * contact page. The Brand Guide lists "choose one canonical email domain" as
   * an open decision -- CONFIRM THIS ADDRESS BEFORE LAUNCH.
   */
  contactEmail: 'hello@imaginationapplied.ai',

  repo: 'https://github.com/jpenzell/imagination-applied',

  /** Fallback social card image. */
  ogImage: '/og-default.png',
} as const;

export const NAV = [
  { href: '/how-we-work/', label: 'How we work' },
  { href: '/keynotes-and-workshops/', label: 'Keynotes & workshops' },
  { href: '/executive-advisory/', label: 'Executive advisory' },
  { href: '/transformation-consulting/', label: 'Transformation consulting' },
  { href: '/publications/', label: 'Research' },
  { href: '/about/', label: 'About' },
  { href: '/contact/', label: 'Contact' },
] as const;

/**
 * The three doors. Titles and Outcome lines are verbatim from the guide,
 * section 7, "Three Ways to Work Together".
 */
export const DOORS = [
  {
    href: '/keynotes-and-workshops/',
    title: 'Keynotes and Workshops',
    for: 'For conferences, leadership meetings, offsites, and learning events that need a shared language and a memorable experience.',
    outcome: 'A room sees the challenge differently and leaves with a move it can use.',
  },
  {
    href: '/executive-advisory/',
    title: 'Executive Advisory',
    for: 'For leaders making consequential choices about AI, adoption, capability, work design, and organizational direction.',
    outcome: 'Clearer interpretation, better decisions, and a rehearsal plan for what comes next.',
  },
  {
    href: '/transformation-consulting/',
    title: 'Transformation Consulting',
    for: 'For organizations ready to move from inspiration to changes in behavior, workflow, learning, or operating practice.',
    outcome:
      'A series of bounded experiments that create evidence, trust, and scalable direction.',
  },
] as const;

/** Guide, section 7, "The Three Practice Modules". Order is canonical. */
export const PRACTICE = [
  {
    name: 'Directing',
    subtitle: 'Getting Everyone in the Same Play',
    oneLiner:
      'Most work does not fail on skill. It fails because everyone is secretly in a different play.',
    move: 'Name what the work is actually about—the point, audience, stakes, and intended effect—before briefing people or AI.',
  },
  {
    name: 'Casting',
    subtitle: 'Casting for Creativity',
    oneLiner: 'Talent belongs to people. Creativity happens between them.',
    move: 'Compose an ensemble with the right blend of familiarity, difference, trust, and productive surprise.',
  },
  {
    name: 'Rehearsing',
    subtitle: 'Rehearsable Change',
    oneLiner: 'Change becomes possible when people can try the future before they are judged by it.',
    move: 'Design bounded attempts that make assumptions and consequences visible, then interpret and revise.',
  },
] as const;

/**
 * The single research publication, keyed to the v3.1.0 package.
 * Title, description and social copy are taken from publication/LAUNCH_KIT.md
 * so the site cannot drift from the reviewed language.
 */
export const PUBLICATIONS = [
  {
    slug: 'adoption-without-confidence',
    title: 'The Developers Using AI Without Trusting It',
    subtitle:
      'What 26,102 current users in Stack Overflow’s 2025 survey reveal about adoption, sentiment, and calibrated skepticism',
    /** LAUNCH_KIT.md, "Meta description". */
    description:
      'A secondary analysis of 26,102 current AI-tool users finds favorable stance toward AI carries substantially more information about daily use than trust in output accuracy.',
    /** LAUNCH_KIT.md, "Open Graph title" / "Open Graph description". */
    ogTitle: 'Developers Are Using AI Without Trusting It',
    ogDescription:
      'Trust in accuracy is not the same thing as willingness to use AI. New analysis of Stack Overflow’s 2025 survey separates the two.',
    formalTitle:
      'Adoption Without Confidence? Favorable Stance, Accuracy Trust, and Reported AI-Use Frequency in the 2025 Stack Overflow Survey',
    author: 'Josh Penzell',
    version: '3.1.0',
    /** CITATION.cff date-released. Update when the DOI is minted. */
    datePublished: '2026-07-24',
    series: 'Open Research Series',
    license: 'MIT',
    licenseUrl: 'https://opensource.org/licenses/MIT',
    /** Set once Zenodo mints it, then mirror into CITATION.cff. */
    doi: null as string | null,
    ogImage: '/publications/adoption-without-confidence/assets/daily-use-by-stance.png',
  },
] as const;
