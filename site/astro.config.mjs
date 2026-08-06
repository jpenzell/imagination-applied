// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// The canonical origin. Every <link rel="canonical">, og:url, sitemap entry
// and RSS link is derived from this, so it is the one place a hostname change
// needs to happen.
export default defineConfig({
  site: 'https://imaginationapplied.ai',
  trailingSlash: 'always',
  integrations: [sitemap()],
  build: {
    // Directory-style output so every page is /path/index.html and the URL
    // with a trailing slash is the real, canonical one.
    format: 'directory',
  },
});
