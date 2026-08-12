// Cloudflare Pages Function — POST /api/contact
//
// The only dynamic endpoint on the site. Every page remains static HTML; this
// exists solely so the contact form has somewhere to post. It requires no
// client JavaScript: the form is a plain HTML POST and this replies with a
// 303 redirect.
//
// Submissions go into the joshpenzell.com leads system rather than to an
// inbox, so an enquiry from here lands in the same place as every other lead,
// with the same scoring, attribution and HubSpot sync. One admin, one CRM.
//
// It posts to /api/partner/leads, not the public /api/leads: that route
// requires a solved proof-of-work token (botCheckMiddleware) which a server
// has no browser to solve. The partner route authenticates with a shared
// secret instead, which is stronger for a caller that can hold one.
//
// Environment (set in the Cloudflare Pages dashboard, never in the repo):
//   PARTNER_SECRET   — must equal IA_PARTNER_SECRET on joshpenzell.com
//   LEADS_ENDPOINT   — optional override, defaults to production
//   CONTACT_FALLBACK — optional email address shown if delivery fails

interface Env {
  PARTNER_SECRET?: string;
  LEADS_ENDPOINT?: string;
  CONTACT_FALLBACK?: string;
}

const DEFAULT_ENDPOINT = 'https://joshpenzell.com/api/partner/leads';
const MAX = { name: 120, email: 200, organization: 200, topic: 40, message: 6000 } as const;

const TOPICS = new Set(['advisory', 'consulting', 'workshop', 'speaking', 'research', 'other']);

function page(title: string, body: string, status: number): Response {
  // Plain HTML so a failure is readable without JavaScript, and styled with
  // the site's own stylesheet so it does not look like a crash.
  return new Response(
    `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title} | Imagination Applied</title>
<link rel="stylesheet" href="/styles.css"></head>
<body><main id="main"><section class="wrap page-head">
<h1>${title}</h1>${body}
</section></main></body></html>`,
    { status, headers: { 'content-type': 'text/html; charset=utf-8' } }
  );
}

function problem(message: string, status: number, env: Env): Response {
  const fallback = env.CONTACT_FALLBACK
    ? ` Or email <a href="mailto:${env.CONTACT_FALLBACK}">${env.CONTACT_FALLBACK}</a>.`
    : '';
  return page(
    'That did not go through',
    `<p class="lede">${message}</p><p><a href="/contact/">Back to the contact form</a>.${fallback}</p>`,
    status
  );
}

function field(form: FormData, key: keyof typeof MAX): string {
  const raw = form.get(key);
  return typeof raw === 'string' ? raw.trim().slice(0, MAX[key]) : '';
}

// Anything that is not a POST gets a plain 405 rather than falling through to
// the static asset handler, which would otherwise serve a page (or the 404) at
// a URL that is not a page at all.
export const onRequest: PagesFunction<Env> = async (ctx) => {
  if (ctx.request.method === 'POST') return onRequestPost(ctx);
  return new Response('Method Not Allowed. This endpoint accepts POST from the contact form.', {
    status: 405,
    headers: { allow: 'POST', 'content-type': 'text/plain; charset=utf-8' },
  });
};

const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return problem('We could not read the form submission.', 400, env);
  }

  // Honeypot: a real person never sees this field. Return the success page so
  // a bot learns nothing from the difference.
  if ((form.get('company_website') as string | null)?.trim()) {
    return Response.redirect(new URL('/contact/thanks/', request.url).href, 303);
  }

  const name = field(form, 'name');
  const email = field(form, 'email');
  const organization = field(form, 'organization');
  const topicRaw = field(form, 'topic');
  const message = field(form, 'message');

  if (!name || !email || !message) {
    return problem('Please include your name, your email address, and a message.', 400, env);
  }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return problem('That email address does not look right.', 400, env);
  }

  const topic = TOPICS.has(topicRaw) ? topicRaw : 'other';

  if (!env.PARTNER_SECRET) {
    console.error('contact: PARTNER_SECRET is not configured');
    return problem('The contact form is not finished being set up.', 500, env);
  }

  let res: Response;
  try {
    res = await fetch(env.LEADS_ENDPOINT ?? DEFAULT_ENDPOINT, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-partner-secret': env.PARTNER_SECRET,
      },
      body: JSON.stringify({
        email,
        name,
        organization,
        topic,
        message,
        sourceDetail: 'imaginationapplied.ai/contact',
      }),
    });
  } catch (err) {
    console.error('contact: leads endpoint unreachable', err);
    return problem('We could not deliver that message. Please try again shortly.', 502, env);
  }

  if (!res.ok) {
    console.error('contact: leads endpoint returned', res.status, await res.text().catch(() => ''));
    // 429 is the rate limiter, and is worth saying plainly rather than
    // reporting as a generic failure the sender cannot act on.
    if (res.status === 429) {
      return problem('That is a few more messages than we allow at once. Please try again in a little while.', 429, env);
    }
    return problem('We could not deliver that message. Please try again shortly.', 502, env);
  }

  return Response.redirect(new URL('/contact/thanks/', request.url).href, 303);
};
