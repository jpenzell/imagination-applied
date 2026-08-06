import rss from '@astrojs/rss';
import type { APIContext } from 'astro';
import { PUBLICATIONS, SITE } from '../consts';

export async function GET(context: APIContext) {
  return rss({
    title: `${SITE.name} — Research`,
    description:
      'Open research from Imagination Applied. Every claim traceable to code, limitations stated in the body rather than a footnote.',
    site: context.site ?? SITE.origin,
    items: PUBLICATIONS.map((pub) => ({
      title: pub.title,
      description: pub.description,
      link: `/publications/${pub.slug}/`,
      pubDate: new Date(`${pub.datePublished}T00:00:00Z`),
      author: pub.author,
    })),
    customData: '<language>en-us</language>',
  });
}
