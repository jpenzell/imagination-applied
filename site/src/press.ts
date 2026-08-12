/**
 * Imagination Applied Press — the catalogue.
 *
 * Every title, subtitle and "Choose this when…" line below is lifted verbatim
 * from the books' own series catalogue page (the "Also in The Forgotten
 * Playbook Library" section shipped inside each EPUB) and from
 * KDP_SUBMISSION_CARD_VOLUME_6.md. Nothing here is written fresh — the
 * catalogue copy went through the series' own editorial standard, and the
 * site should not invent a second version of it.
 *
 * ⚠️ No purchase links. As of 2026-08-12 these are upload-certified candidates,
 * not published books — the package's own words: "certified upload candidates…
 * before clicking Publish." A "Buy" link would be a placeholder, and the launch
 * brief is explicit that placeholders never ship. Add the retailer link per
 * volume once it is genuinely live.
 */

export interface Volume {
  volume: number;
  title: string;
  subtitle: string;
  /** The series' own "Choose this when…" line. */
  chooseWhen: string;
  pages: number;
  /** Set to the retailer URL once the volume is actually published. */
  url: string | null;
}

/** Series principle, verbatim from the catalogue page. */
export const SERIES_PRINCIPLE =
  'Rescue what still works. Retire what does not. Make the useful part easy to act on.';

export const SERIES_NOTE =
  'Additional volumes recover overlooked public-domain ideas for modern families, educators, facilitators, and communities.';

export const FORGOTTEN_PLAYBOOK: Volume[] = [
  {
    volume: 1,
    title: 'The Screen-Free Group Games Handbook',
    subtitle: '60 Cooperative Activities for Classrooms, Camps, Meetings, and Youth Groups',
    chooseWhen:
      'Choose this when a group needs connection, coordination, listening, movement, reflection, or closure—and you want activities that do not rely on public elimination or forced disclosure.',
    pages: 112,
    url: null,
  },
  {
    volume: 2,
    title: 'How to Collect Family Stories',
    subtitle: 'An Oral-History Field Guide for Recording, Preserving, and Sharing What Matters',
    chooseWhen:
      'Choose this when someone knows something you will never be able to Google—and you want to record it with consent, context, and a preservation plan.',
    pages: 88,
    url: null,
  },
  {
    volume: 3,
    title: 'The Vintage Maker Book',
    subtitle: '30 Old-School Crafts, Toys, Celebrations, and Adventures Rebuilt for Modern Kids',
    chooseWhen:
      'Choose this when children or groups need a screen-light project they can make, test, revise, and understand—not merely copy.',
    pages: 112,
    url: null,
  },
  {
    volume: 4,
    title: 'The Boredom Rescue Book',
    subtitle: '100 Screen-Free Things Kids Can Actually Do',
    chooseWhen:
      'Choose this when a child, family, classroom, library, camp, or after-school group needs a screen-free beginning matched to time, supplies, energy, independence, noise, company, or the kind of bored they are actually experiencing.',
    pages: 154,
    url: null,
  },
  {
    volume: 5,
    title: 'Cardboard Engineering for Kids',
    subtitle: '24 Builds From Shipping Boxes',
    chooseWhen:
      'Choose this when ordinary shipping boxes should become testable structures, mechanisms, games, and useful objects—and you want makers to plan, test, observe, and revise.',
    pages: 77,
    url: null,
  },
  {
    volume: 6,
    title: 'Raising a Lifelong Reader',
    subtitle: '36 Practical Invitations That Help Children Choose Books',
    chooseWhen:
      'Choose this when a child needs books, formats, places, and shared routines that feel possible to return to—and you want interest kept separate from skill, with explicit instruction still in view.',
    pages: 110,
    url: null,
  },
];

/**
 * The book. Deliberately a forthcoming listing and nothing more.
 *
 * Its own HANDOFF.md lists the next steps as Josh's first read of the applied
 * version, then a human editor and beta readers — neither has happened. An
 * acquisitions editor's verdict was "ACQUIRE WITH REVISIONS", so publishing it
 * here would also forfeit a traditional route that is currently open. The
 * Brand Guide's standing line is "forthcoming author of Artistic Intelligence";
 * this page says exactly that and no more. No manuscript, no excerpt.
 */
export const BOOK = {
  title: 'Artistic Intelligence',
  subtitle: 'A Manifesto',
  author: 'Josh Penzell',
  status: 'Forthcoming',
  /** Guide, section 4, "Public Definition". */
  premise:
    'Artistic Intelligence is what we use when the answer is not waiting to be found—it has to be made.',
} as const;
