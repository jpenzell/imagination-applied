// GENERATED FILE — do not edit by hand.
//
// Source: imagination-applied repo, site/src/lib/blocks.ts
// Regenerate with: npm run emit:blocks   (in that repo)
//
// These blocks are the editable surface of imaginationapplied.ai. They appear
// in the Site Content admin tab like any other block. Publishing one fires the
// Cloudflare deploy hook, which rebuilds that site with the new copy.
//
// The `ia.*` namespace keeps them from colliding with joshpenzell.com's own
// blocks in the shared site_content table.

import type { SiteContentBlockDef } from "./site-content-registry";

export const IMAGINATION_APPLIED_BLOCKS: SiteContentBlockDef[] = [
  {
    "blockId": "ia.seo.home.artistic-intelligence.v2",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Home page SEO",
    "defaultValue": {
      "title": "Imagination Applied | AI Work Rehearsals for Teams",
      "description": "Imagination Applied helps leaders and teams rehearse consequential AI work before the consequences are real."
    }
  },
  {
    "blockId": "ia.seo.how-we-work.v2",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "How we work SEO",
    "defaultValue": {
      "title": "How we work",
      "description": "TheaterThink is our rehearsal-based practice: direct the work, cast the ensemble, rehearse before the stakes are irreversible. Direct, Cast, Rehearse, Interpret."
    }
  },
  {
    "blockId": "ia.seo.keynotes.v2",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Keynotes and workshops SEO",
    "defaultValue": {
      "title": "Keynotes and workshops",
      "description": "Josh-led keynotes and rehearsal-based workshops on Artistic Intelligence, creativity, leadership, and the age of AI."
    }
  },
  {
    "blockId": "ia.seo.advisory.v2",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Executive advisory SEO",
    "defaultValue": {
      "title": "Transformation Advisory",
      "description": "For leaders making consequential choices about direction, capability, work design, AI, and organizational change."
    }
  },
  {
    "blockId": "ia.seo.consulting.v2",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Transformation consulting SEO",
    "defaultValue": {
      "title": "The Rehearsal Room",
      "description": "Build working proof, learn through bounded experiments, and transfer the practice until your team can run it without us."
    }
  },
  {
    "blockId": "ia.seo.about.v2",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "About SEO",
    "defaultValue": {
      "title": "About",
      "description": "Imagination Applied is the company that brings Artistic Intelligence into organizations through AI work rehearsals, keynotes and Transformation Advisory."
    }
  },
  {
    "blockId": "ia.seo.publications",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Research index SEO",
    "defaultValue": {
      "title": "Research",
      "description": "Open research from Imagination Applied, with traceable claims, stated limitations, reproducible analysis, and released checksums."
    }
  },
  {
    "blockId": "ia.seo.contact.v2",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Contact SEO",
    "defaultValue": {
      "title": "Contact",
      "description": "Tell us what the work is actually about. Imagination Applied works with leaders and teams on AI work rehearsals, ongoing practice, keynotes and advisory."
    }
  },
  {
    "blockId": "ia.home.hero.headline.v2",
    "type": "text",
    "page": "Imagination Applied — Home",
    "label": "Hero headline (the final word renders in orange)",
    "defaultValue": "Do not roll out the future. Rehearse it."
  },
  {
    "blockId": "ia.home.hero.lede.v2",
    "type": "text",
    "page": "Imagination Applied — Home",
    "label": "Hero supporting line",
    "defaultValue": "Bring one consequential workflow and the people who own it. We help your team direct AI, test human judgment and decide what to pilot, revise or stop."
  },
  {
    "blockId": "ia.home.tension.heading",
    "type": "text",
    "page": "Imagination Applied — Home",
    "label": "Tension section heading",
    "defaultValue": "Possibility is abundant. Direction is not."
  },
  {
    "blockId": "ia.home.tension.body",
    "type": "richtext",
    "page": "Imagination Applied — Home",
    "label": "Tension section body (HTML)",
    "defaultValue": "<p>Organizations are surrounded by possibility and starved for direction. They can generate more options, more content, and more analysis than ever. But output does not produce shared meaning, good judgment, or movement.</p><p>This is true in innovation, learning, strategy, culture, and change. AI accelerates it: a model can produce a beautiful answer to a question nobody meant to ask.</p><p>The decision—what is worth making—lives in interpretation. In the point of view you bring, the ensemble you compose, and what you learn when the idea finally has to move.</p>"
  },
  {
    "blockId": "ia.home.research.blurb",
    "type": "text",
    "page": "Imagination Applied — Home",
    "label": "Research section blurb",
    "defaultValue": "Advice about AI adoption is cheap. We test ours, publish the code and the checksums, and state the limitations in the body of the work rather than in a footnote."
  },
  {
    "blockId": "ia.doors.items.v2",
    "type": "list",
    "page": "Imagination Applied — Ways to work together",
    "label": "The four ways to work together",
    "itemTitleKey": "title",
    "itemFields": [
      {
        "key": "title",
        "label": "Title",
        "type": "text"
      },
      {
        "key": "href",
        "label": "Page path",
        "type": "url"
      },
      {
        "key": "for",
        "label": "Who it is for",
        "type": "textarea"
      },
      {
        "key": "outcome",
        "label": "Outcome",
        "type": "textarea"
      }
    ],
    "defaultValue": [
      {
        "href": "/learning-design/",
        "title": "Learning Experience Design & Advisory",
        "for": "Design useful learning with your team, from a focused review to a complete course or curriculum.",
        "outcome": "Clear learning design, practical experiences and support through delivery. AI is optional."
      },
      {
        "href": "/keynotes-and-workshops/",
        "title": "Keynotes",
        "for": "Create shared language for leadership, creativity and AI with Josh in the room.",
        "outcome": "A memorable experience and a next move people can use."
      },
      {
        "href": "/rehearsal-room/",
        "title": "The Rehearsal Room",
        "for": "Bring one real workflow and the people who own it. Try the work before the stakes are real.",
        "outcome": "Observed risks, a rehearsed workflow and a Pilot / Revise / Stop decision."
      },
      {
        "href": "/rehearsal-room/#practice",
        "title": "Rehearsal Practice",
        "for": "Build capability through recurring scenes, coaching and failure drills.",
        "outcome": "Evidence of performance and a practice the team can keep using."
      },
      {
        "href": "/executive-advisory/",
        "title": "Transformation Advisory",
        "for": "Work through consequential choices about AI, work design and human control.",
        "outcome": "Direction, governance and a rehearsal plan for what comes next."
      }
    ]
  },
  {
    "blockId": "ia.global.description.v2",
    "type": "text",
    "page": "Imagination Applied — Global",
    "label": "Company description (footer, meta, JSON-LD)",
    "defaultValue": "Imagination Applied helps leaders and teams rehearse consequential AI work before the consequences are real."
  },
  {
    "blockId": "ia.global.contactEmail",
    "type": "text",
    "page": "Imagination Applied — Global",
    "label": "Contact email address",
    "defaultValue": "josh@imaginationapplied.ai"
  }
];
