// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// The canonical origin. Every <link rel="canonical">, og:url, sitemap entry
// and RSS link is derived from this, so it is the one place a hostname change
// needs to happen.
export default defineConfig({
  site: 'https://imaginationapplied.ai',
  trailingSlash: 'always',
  integrations: [
    sitemap({
      // The 404 is a real built page but not a destination, so it stays out of
      // the sitemap (it also carries noindex).
      filter: (page) => !page.endsWith('/thanks/') && !['/404/', '/contact/thanks/', '/transformation-consulting/', '/press/forgotten-playbook-library/', '/press/the-past-tests-you/', '/press/stories-that-rehearsed-tomorrow/'].some(path => page.endsWith(path)),
    }),
  ],
  build: {
    // Directory-style output so every page is /path/index.html and the URL
    // with a trailing slash is the real, canonical one.
    format: 'directory',
  },
});
