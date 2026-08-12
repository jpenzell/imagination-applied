/**
 * Imagination Applied Press — the catalogue.
 *
 * ── Why this file exists ──────────────────────────────────────────────────
 *
 * The books live as ~40 near-identical dated ZIPs in ~/Downloads with no
 * registry of which is current. That is why the catalogue goes stale: there is
 * no place that is *supposed* to be right, so nothing ever gets corrected.
 * This file is that place. It is the one list of what the Press has, what state
 * each title is in, and where its package lives.
 *
 * Same pattern as site/src/lib/blocks.ts: one definition, consumed by the site.
 * When a title's status changes, change it HERE and the pages follow.
 *
 * ── Rules ────────────────────────────────────────────────────────────────
 *
 * • Copy is verbatim from each title's own KDP submission card or series
 *   catalogue page. The site does not author a second version of book copy
 *   that already passed the series' editorial standard.
 * • `url` stays null until the title is genuinely on sale. A "coming soon"
 *   button is a placeholder, and placeholders do not ship.
 * • `status` is the honest state, not the hoped-for one. If a title is on hold,
 *   it says so.
 *
 * Sources: Forgotten_Playbook_Library_Volumes_1-6_Complete_FINAL_v3.2.0,
 * The_Past_Tests_You_Volume_{1..4}_Publish_Ready,
 * Stories_That_Rehearsed_Tomorrow_3_Volume_Bundle (all in ~/Downloads,
 * 2026-08-07 → 2026-08-11).
 */

export type TitleStatus =
  /** Finished and through production; not yet on sale. */
  | 'ready'
  /** Deliberately held back — reason must be given. */
  | 'hold'
  /** On sale; `url` must be set. */
  | 'published'
  /** Written but not through production review. */
  | 'forthcoming';

export interface Title {
  volume: number;
  title: string;
  subtitle: string;
  /** One line, verbatim from the book's own catalogue or submission copy. */
  blurb: string;
  pages?: number;
  status: TitleStatus;
  /** Shown when status is 'hold'. */
  holdReason?: string;
  /** Retailer URL. Null until genuinely on sale. */
  url: string | null;
}

export interface Series {
  slug: string;
  name: string;
  tagline: string;
  /** Who the series is actually for. */
  audience: string;
  principle?: string;
  titles: Title[];
}

export const SERIES: Series[] = [
  {
    slug: 'forgotten-playbook-library',
    name: 'The Forgotten Playbook Library',
    tagline:
      'Overlooked public-domain ideas, rebuilt for modern families, educators, facilitators and communities.',
    audience: 'Anyone running a room: parents, teachers, librarians, camp and group leaders.',
    principle:
      'Rescue what still works. Retire what does not. Make the useful part easy to act on.',
    titles: [
      {
        volume: 1,
        title: 'The Screen-Free Group Games Handbook',
        subtitle: '60 Cooperative Activities for Classrooms, Camps, Meetings, and Youth Groups',
        blurb:
          'Choose this when a group needs connection, coordination, listening, movement, reflection, or closure—and you want activities that do not rely on public elimination or forced disclosure.',
        pages: 112,
        status: 'ready',
        url: null,
      },
      {
        volume: 2,
        title: 'How to Collect Family Stories',
        subtitle: 'An Oral-History Field Guide for Recording, Preserving, and Sharing What Matters',
        blurb:
          'Choose this when someone knows something you will never be able to Google—and you want to record it with consent, context, and a preservation plan.',
        pages: 88,
        status: 'ready',
        url: null,
      },
      {
        volume: 3,
        title: 'The Vintage Maker Book',
        subtitle: '30 Old-School Crafts, Toys, Celebrations, and Adventures Rebuilt for Modern Kids',
        blurb:
          'Choose this when children or groups need a screen-light project they can make, test, revise, and understand—not merely copy.',
        pages: 112,
        status: 'ready',
        url: null,
      },
      {
        volume: 4,
        title: 'The Boredom Rescue Book',
        subtitle: '100 Screen-Free Things Kids Can Actually Do',
        blurb:
          'Choose this when a child, family, classroom, library, camp, or after-school group needs a screen-free beginning matched to time, supplies, energy, independence, noise, company, or the kind of bored they are actually experiencing.',
        pages: 154,
        status: 'ready',
        url: null,
      },
      {
        volume: 5,
        title: 'Cardboard Engineering for Kids',
        subtitle: '24 Builds From Shipping Boxes',
        blurb:
          'Choose this when ordinary shipping boxes should become testable structures, mechanisms, games, and useful objects—and you want makers to plan, test, observe, and revise.',
        pages: 77,
        status: 'ready',
        url: null,
      },
      {
        volume: 6,
        title: 'Raising a Lifelong Reader',
        subtitle: '36 Practical Invitations That Help Children Choose Books',
        blurb:
          'Choose this when a child needs books, formats, places, and shared routines that feel possible to return to—and you want interest kept separate from skill, with explicit instruction still in view.',
        pages: 110,
        status: 'ready',
        url: null,
      },
    ],
  },
  {
    slug: 'the-past-tests-you',
    name: 'The Past Tests You',
    tagline: 'First answer the archive. Then judge the archive.',
    audience:
      'Readers who want history to be playable rather than recited — and are willing to be graded by it.',
    titles: [
      {
        volume: 1,
        title: 'Could You Pass in 1900?',
        subtitle: 'The Past Tests You, Book 1',
        blurb:
          'Could you pass in 1900? The more revealing question is whether the answers still deserve to pass today.',
        status: 'ready',
        url: null,
      },
      {
        volume: 2,
        title: 'Could You Get the Job in 1900?',
        subtitle: 'The Past Tests You, Book 2',
        blurb:
          'Could you win a federal desk, carry the mail, inspect a crowded city, or even reach the examination room in 1900?',
        status: 'ready',
        url: null,
      },
      {
        volume: 3,
        title: 'Could You Run the House in 1900?',
        subtitle: 'The Past Tests You, Book 3',
        blurb:
          'Could you keep a turn-of-the-century household fed, lit, clean, clothed—and solvent?',
        status: 'ready',
        url: null,
      },
      {
        volume: 4,
        title: 'Could You Behave in 1900?',
        subtitle: 'The Past Tests You, Book 4',
        blurb:
          'Could you survive an introduction, a calling card, a formal dinner, a courtship, a streetcar—and the hidden rules of respectable society in 1900? 100 source-traced encounters: predict whether each rule is right then, right now, both, or broken.',
        status: 'ready',
        url: null,
      },
    ],
  },
  {
    slug: 'stories-that-rehearsed-tomorrow',
    name: 'Stories That Rehearsed Tomorrow',
    tagline:
      'Annotated documentary editions of the moments when people imagined a technology before they had it.',
    audience:
      'Readers of technology history — and the closest of the four series to the practice, since the argument is that we rehearse the future before we build it.',
    titles: [
      {
        volume: 1,
        title: 'Thinking Machines Before AI',
        subtitle: 'Stories That Rehearsed Tomorrow',
        blurb: 'What people imagined machines would think, long before any machine could.',
        status: 'hold',
        holdReason:
          'Kindle is release-ready for a United States-only posture; the paperback is held pending qualified Canadian rights review of every story and documentary image.',
        url: null,
      },
      {
        volume: 2,
        title: 'Robot Servants Before Robots',
        subtitle: 'Stories That Rehearsed Tomorrow',
        blurb: 'The household robot as it was dreamed, decades before it could be built.',
        status: 'hold',
        holdReason:
          'Kindle is release-ready for a United States-only posture; the paperback is held pending qualified Canadian rights review of every story and documentary image.',
        url: null,
      },
      {
        volume: 3,
        title: 'Connected Before the Internet',
        subtitle: 'Stories That Rehearsed Tomorrow',
        blurb: 'Networks, distance and instant contact, imagined before the wires existed.',
        status: 'hold',
        holdReason:
          'Kindle is release-ready for a United States-only posture; the paperback is held pending qualified Canadian rights review of every story and documentary image.',
        url: null,
      },
    ],
  },
];

export const TOTAL_TITLES = SERIES.reduce((n, s) => n + s.titles.length, 0);

/**
 * The book. Deliberately a forthcoming listing and nothing more.
 *
 * Its own HANDOFF.md still lists Josh's first read of the applied version and a
 * human editor/beta readers as outstanding, and an acquisitions editor's
 * verdict was "ACQUIRE WITH REVISIONS" — publishing it here would close a
 * traditional route that is currently open.
 */
export const BOOK = {
  title: 'Artistic Intelligence',
  subtitle: 'A Manifesto',
  author: 'Josh Penzell',
  status: 'Forthcoming',
  premise:
    'Artistic Intelligence is what we use when the answer is not waiting to be found—it has to be made.',
} as const;
