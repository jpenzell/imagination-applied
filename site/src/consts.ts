// Site-wide constants.
//
// Copy in this file is drawn from Josh_Penzell_Imagination_Applied_Brand_Guide_2026.docx
// (v2.0, September 14, 2026), which the guide itself declares authoritative over older
// website copy. Where a line is quoted from the guide it is marked. Do not
// replace guide language with a paraphrase without updating the guide first.

export const SITE = {
  /** Legal/brand name. No trademark symbol -- guide, Naming and Trademark Rules. */
  name: 'Imagination Applied',
  origin: 'https://imaginationapplied.ai',

  /** Guide, section 3, "Recommended description". */
  description:
    'Imagination Applied helps leaders and teams rehearse consequential AI work before the consequences are real.',

  /** Guide, section 12, "Company Boilerplate". */
  boilerplate:
    'Imagination Applied is the company that brings Artistic Intelligence into organizations. Founded by keynote speaker, advisor, and theater director Josh Penzell, it helps leaders and teams rehearse consequential AI work before the consequences are real. The Rehearsal Room brings people, workflows and AI together through the TheaterThink® method: Direct, Cast, Rehearse, Interpret.',

  /** Company promise. */
  hero: 'Do not roll out the future. Rehearse it.',

  /** Guide, section 3, "Optional internal line". */
  tagline: 'Artistic Intelligence, applied.',

  founder: 'Josh Penzell',
  founderSite: 'https://joshpenzell.com',
  linkedin: 'https://www.linkedin.com/company/imaginationapplied',

  /**
   * The address shown on the contact page. Confirmed by Josh 2026-08-10.
   * The live value is the ia.global.contactEmail block; this is the fallback.
   */
  contactEmail: 'josh@imaginationapplied.ai',

  repo: 'https://github.com/jpenzell/imagination-applied',

  /** Fallback social card image. */
  ogImage: '/og-default.png',
} as const;

export const NAV = [
  { href: '/rehearsal-room/', label: 'The Rehearsal Room' },
  { href: '/learning-design/', label: 'Learning design' },
  { href: '/how-we-work/', label: 'How we work' },
  { href: '/keynotes-and-workshops/', label: 'Keynotes' },
  { href: '/executive-advisory/', label: 'Advisory' },
  { href: '/lab/', label: 'Lab' },
  { href: '/publications/', label: 'Research' },
  { href: '/about/', label: 'About' },
  { href: '/contact/', label: 'Contact' },
] as const;

export const DOORS = [
 {href:'/learning-design/',title:'Learning Experience Design & Advisory',for:'Design useful learning with your team, from a focused review to a complete course or curriculum.',outcome:'Clear learning design, practical experiences and support through delivery. AI is optional.'},
 {href:'/keynotes-and-workshops/',title:'Keynotes',for:'Create shared language for leadership, creativity and AI with Josh in the room.',outcome:'A memorable experience and a next move people can use.'},
 {href:'/rehearsal-room/',title:'The Rehearsal Room',for:'Bring one real workflow and the people who own it. Try the work before the stakes are real.',outcome:'Observed risks, a rehearsed workflow and a Pilot / Revise / Stop decision.'},
 {href:'/rehearsal-room/#practice',title:'Rehearsal Practice',for:'Build capability through recurring scenes, coaching and failure drills.',outcome:'Evidence of performance and a practice the team can keep using.'},
 {href:'/executive-advisory/',title:'Transformation Advisory',for:'Work through consequential choices about AI, work design and human control.',outcome:'Direction, governance and a rehearsal plan for what comes next.'},
] as const;

/** Canonical working arc, brand guide v2.0. */
export const PRACTICE = [
 {name:'Direct',subtitle:'What play are we in?',oneLiner:'Name what matters before asking people or AI to act.',move:'Define the point, audience, stakes, boundaries and evidence of a good result.'},
 {name:'Cast',subtitle:'Who and what belong in the room?',oneLiner:'Compose the ensemble the work needs.',move:'Bring together people, AI, data, tools, permissions and different perspectives.'},
 {name:'Rehearse',subtitle:'What happens when the work moves?',oneLiner:'Try the workflow while the cost of being wrong is low.',move:'Run a normal scene and a pressure scene, including ambiguity, exceptions and failure.'},
 {name:'Interpret',subtitle:'What did the attempt teach us?',oneLiner:'Read the evidence and decide what deserves to happen next.',move:'Notice consequences and choose: Pilot, Revise or Stop.'},
] as const;

/** Current research revision. The frozen 2025 release remains linked on its page. */
export const PUBLICATIONS = [
  {
    slug: 'adoption-without-confidence',
    title: 'Adoption Without Confidence',
    subtitle: 'AI use, attitude and trust in the 2025 and 2026 Stack Overflow surveys',
    description:
      'Among current AI users in the 2026 analysis, 54% of very unfavorable users reported daily use, compared with 93% of very favorable users. The survey redesign limits comparisons with 2025.',
    ogTitle: 'Daily AI use can coexist with an unfavorable view of the tools',
    ogDescription:
      'The 2026 Stack Overflow analysis separates use, attitude and conditions for trust. Read the findings, methods and limits.',
    formalTitle:
      'Adoption Without Confidence? Favorable Stance, Trust, and Reported AI-Use Frequency in the 2025 and 2026 Stack Overflow Surveys',
    author: 'Josh Penzell',
    version: '3.2.0',
    datePublished: '2026-08-12',
    dateModified: '2026-11-07',
    series: 'Open Research Series',
    license: 'MIT',
    licenseUrl: 'https://opensource.org/licenses/MIT',
    doi: null as string | null,
    previousVersionDoi: '10.5281/zenodo.21896528',
    conceptDoi: '10.5281/zenodo.21896527',
    researchRepo: 'https://github.com/jpenzell/ai-adoption-paradox/tree/v3.2.0',
    researchRelease: 'https://github.com/jpenzell/ai-adoption-paradox/releases/tag/v3.2.0',
    ogImage: '/publications/adoption-without-confidence/daily-use-by-attitude-2026.png',
  },
] as const;
