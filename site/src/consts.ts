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
    /**
     * Publication date: the day this became publicly available and citable at
     * imaginationapplied.ai. Kept in step with the root CITATION.cff so the
     * page, the citation and the DOI record cannot disagree. The v3.1.0
     * package build date (2026-07-24) lives in RELEASE_NOTES.md.
     */
    datePublished: '2026-08-12',
    series: 'Open Research Series',
    license: 'MIT',
    licenseUrl: 'https://opensource.org/licenses/MIT',
    /**
     * Version DOI — cites this exact release, which is what a reproducibility
     * claim needs. The concept DOI below always resolves to the latest version.
     * Both are recorded in the root CITATION.cff.
     */
    doi: '10.5281/zenodo.21896528' as string | null,
    conceptDoi: '10.5281/zenodo.21896527',
    ogImage: '/publications/adoption-without-confidence/assets/daily-use-by-stance.png',
  },
] as const;
