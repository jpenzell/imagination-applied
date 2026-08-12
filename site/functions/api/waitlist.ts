// Cloudflare Pages Function — POST /api/waitlist
//
// Book-interest signups. Deliberately email-only: asking for a name and a
// message to join a waitlist is friction that costs signups and buys nothing.
//
// Routes into the same joshpenzell.com leads system as the contact form, with
// its own activity source so book interest can be segmented from enquiries.
// Same shared-secret auth, same rate limiter, same fail-closed behaviour.

interface Env {
  PARTNER_SECRET?: string;
  LEADS_ENDPOINT?: string;
  CONTACT_FALLBACK?: string;
}

const DEFAULT_ENDPOINT = 'https://joshpenzell.com/api/partner/leads';

function page(title: string, body: string, status: number): Response {
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
    `<p class="lede">${message}</p><p><a href="/press/artistic-intelligence/">Back to the book</a>.${fallback}</p>`,
    status
  );
}

export const onRequest: PagesFunction<Env> = async (ctx) => {
  if (ctx.request.method === 'POST') return handle(ctx);
  return new Response('Method Not Allowed. This endpoint accepts POST from the waitlist form.', {
    status: 405,
    headers: { allow: 'POST', 'content-type': 'text/plain; charset=utf-8' },
  });
};

const handle: PagesFunction<Env> = async ({ request, env }) => {
  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return problem('We could not read that submission.', 400, env);
  }

  // Honeypot — a person never sees this field.
  if ((form.get('company_website') as string | null)?.trim()) {
    return Response.redirect(new URL('/press/artistic-intelligence/thanks/', request.url).href, 303);
  }

  const raw = form.get('email');
  const email = typeof raw === 'string' ? raw.trim().slice(0, 200) : '';
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return problem('That email address does not look right.', 400, env);
  }

  const listRaw = form.get('list');
  const list = listRaw === 'forgotten-playbook-library' ? 'forgotten-playbook-library' : 'artistic-intelligence';

  if (!env.PARTNER_SECRET) {
    console.error('waitlist: PARTNER_SECRET is not configured');
    return problem('The waitlist is not finished being set up.', 500, env);
  }

  let res: Response;
  try {
    res = await fetch(env.LEADS_ENDPOINT ?? DEFAULT_ENDPOINT, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-partner-secret': env.PARTNER_SECRET },
      body: JSON.stringify({
        email,
        topic: 'book-waitlist',
        message: `Waitlist signup: ${list}`,
        sourceDetail: `imaginationapplied.ai/press/${list}`,
      }),
    });
  } catch (err) {
    console.error('waitlist: leads endpoint unreachable', err);
    return problem('We could not record that just now. Please try again shortly.', 502, env);
  }

  if (!res.ok) {
    if (res.status === 429) {
      return problem('That is a few too many attempts at once. Please try again shortly.', 429, env);
    }
    console.error('waitlist: leads endpoint returned', res.status, await res.text().catch(() => ''));
    return problem('We could not record that just now. Please try again shortly.', 502, env);
  }

  return Response.redirect(new URL('/press/artistic-intelligence/thanks/', request.url).href, 303);
};
