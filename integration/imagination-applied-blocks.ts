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
    "blockId": "ia.seo.home",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Home page SEO",
    "defaultValue": {
      "title": "Imagination Applied",
      "description": "Imagination Applied helps leaders and teams turn uncertainty into direction through keynotes, advisory work, and rehearsal-based transformation."
    }
  },
  {
    "blockId": "ia.seo.how-we-work",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "How we work SEO",
    "defaultValue": {
      "title": "How we work",
      "description": "TheaterThink is our rehearsal-based practice: direct the work, cast the ensemble, rehearse before the stakes are irreversible. Three moves, in order."
    }
  },
  {
    "blockId": "ia.seo.keynotes",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Keynotes and workshops SEO",
    "defaultValue": {
      "title": "Keynotes and workshops",
      "description": "For conferences, leadership meetings, offsites, and learning events that need a shared language and a memorable experience."
    }
  },
  {
    "blockId": "ia.seo.advisory",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Executive advisory SEO",
    "defaultValue": {
      "title": "Executive advisory",
      "description": "For leaders making consequential choices about AI, adoption, capability, work design, and organizational direction."
    }
  },
  {
    "blockId": "ia.seo.consulting",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Transformation consulting SEO",
    "defaultValue": {
      "title": "Transformation consulting",
      "description": "For organizations ready to move from inspiration to changes in behavior, workflow, learning, or operating practice."
    }
  },
  {
    "blockId": "ia.seo.about",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "About SEO",
    "defaultValue": {
      "title": "About",
      "description": "Imagination Applied brings Artistic Intelligence into organizations through live experiences, executive advisory, and rehearsal-based transformation. Founded by Josh Penzell."
    }
  },
  {
    "blockId": "ia.seo.publications",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Research index SEO",
    "defaultValue": {
      "title": "Research",
      "description": "Open research from Imagination Applied. Every claim traceable to code, limitations stated in the body rather than a footnote, and the analysis released with its checksums."
    }
  },
  {
    "blockId": "ia.seo.contact",
    "type": "seo",
    "page": "Imagination Applied — SEO",
    "label": "Contact SEO",
    "defaultValue": {
      "title": "Contact",
      "description": "Tell us what the work is actually about. Imagination Applied works with leaders and teams on AI adoption, advisory, and rehearsal-based transformation."
    }
  },
  {
    "blockId": "ia.home.hero.headline",
    "type": "text",
    "page": "Imagination Applied — Home",
    "label": "Hero headline (the final word renders in orange)",
    "defaultValue": "Don’t Just Prompt. Direct."
  },
  {
    "blockId": "ia.home.hero.lede",
    "type": "text",
    "page": "Imagination Applied — Home",
    "label": "Hero supporting line",
    "defaultValue": "AI can make almost anything. The real leadership challenge is deciding what is worth making—and creating the conditions to make it real."
  },
  {
    "blockId": "ia.home.tension.heading",
    "type": "text",
    "page": "Imagination Applied — Home",
    "label": "Tension section heading",
    "defaultValue": "The problem is not capability. It is direction."
  },
  {
    "blockId": "ia.home.tension.body",
    "type": "richtext",
    "page": "Imagination Applied — Home",
    "label": "Tension section body (HTML)",
    "defaultValue": "<p>Organizations are surrounded by possibility and starved for direction. They can generate more options, more content, more analysis than ever. But more output does not produce shared meaning, good judgment, or movement.</p><p>Teams can be competent and still be in different plays. Leaders can move quickly and still move in the wrong direction. AI can produce a beautiful answer to a question nobody meant to ask.</p><p>That decision—what is worth making—is not hidden inside a better prompt. It lives in interpretation. In the point of view you bring, the people and tools you put in the room, and what you learn when the idea finally has to move.</p>"
  },
  {
    "blockId": "ia.home.research.blurb",
    "type": "text",
    "page": "Imagination Applied — Home",
    "label": "Research section blurb",
    "defaultValue": "Advice about AI adoption is cheap. We test ours, publish the code and the checksums, and state the limitations in the body of the work rather than in a footnote."
  },
  {
    "blockId": "ia.doors.items",
    "type": "list",
    "page": "Imagination Applied — Ways to work together",
    "label": "The three doors",
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
        "title": "Keynotes and Workshops",
        "href": "/keynotes-and-workshops/",
        "for": "For conferences, leadership meetings, offsites, and learning events that need a shared language and a memorable experience.",
        "outcome": "A room sees the challenge differently and leaves with a move it can use."
      },
      {
        "title": "Executive Advisory",
        "href": "/executive-advisory/",
        "for": "For leaders making consequential choices about AI, adoption, capability, work design, and organizational direction.",
        "outcome": "Clearer interpretation, better decisions, and a rehearsal plan for what comes next."
      },
      {
        "title": "Transformation Consulting",
        "href": "/transformation-consulting/",
        "for": "For organizations ready to move from inspiration to changes in behavior, workflow, learning, or operating practice.",
        "outcome": "A series of bounded experiments that create evidence, trust, and scalable direction."
      }
    ]
  },
  {
    "blockId": "ia.global.description",
    "type": "text",
    "page": "Imagination Applied — Global",
    "label": "Company description (footer, meta, JSON-LD)",
    "defaultValue": "Imagination Applied helps leaders and teams turn uncertainty into direction through keynotes, advisory work, and rehearsal-based transformation."
  },
  {
    "blockId": "ia.global.contactEmail",
    "type": "text",
    "page": "Imagination Applied — Global",
    "label": "Contact email address",
    "defaultValue": "josh@imaginationapplied.ai"
  }
];
