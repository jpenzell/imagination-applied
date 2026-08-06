// Cloudflare Pages Function — POST /api/contact
//
// The only dynamic endpoint on the site. Every page remains static HTML; this
// exists solely so the contact form has somewhere to post. It requires no
// client JavaScript: the form is a plain HTML POST and this replies with a
// 303 redirect.
//
// Environment (set these in the Cloudflare Pages dashboard, not in the repo):
//   RESEND_API_KEY  — API key for the transactional email provider
//   CONTACT_TO      — destination address for submissions
//   CONTACT_FROM    — verified sender, e.g. "Website <noreply@imaginationapplied.ai>"

interface Env {
  RESEND_API_KEY?: string;
  CONTACT_TO?: string;
  CONTACT_FROM?: string;
}

const MAX = { name: 120, email: 200, organization: 200, topic: 40, message: 6000 } as const;

const TOPICS = new Set([
  'advisory',
  'consulting',
  'workshop',
  'speaking',
  'research',
  'other',
]);

function problem(message: string, status: number): Response {
  // Plain HTML so the failure is readable without JavaScript.
  const body = `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Message not sent | Imagination Applied</title>
<link rel="stylesheet" href="/styles.css"></head>
<body><main id="main"><section class="wrap page-head">
<h1>That did not go through</h1>
<p class="lede">${message}</p>
<p><a href="/contact/">Back to the contact form</a></p>
</section></main></body></html>`;
  return new Response(body, {
    status,
    headers: { 'content-type': 'text/html; charset=utf-8' },
  });
}

function field(form: FormData, key: keyof typeof MAX): string {
  const raw = form.get(key);
  return typeof raw === 'string' ? raw.trim().slice(0, MAX[key]) : '';
}

export const onRequestPost: PagesFunction<Env> = async ({ request, env }) => {
  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return problem('We could not read the form submission.', 400);
  }

  // Honeypot: a real person never sees this field, so anything in it is a bot.
  // Return the success redirect so the bot has nothing to learn from the result.
  if ((form.get('company_website') as string | null)?.trim()) {
    return Response.redirect(new URL('/contact/thanks/', request.url).href, 303);
  }

  const name = field(form, 'name');
  const email = field(form, 'email');
  const organization = field(form, 'organization');
  const topicRaw = field(form, 'topic');
  const message = field(form, 'message');

  if (!name || !email || !message) {
    return problem('Please include your name, your email address, and a message.', 400);
  }
  // Deliberately permissive: the delivery attempt is the real validation.
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return problem('That email address does not look right.', 400);
  }

  const topic = TOPICS.has(topicRaw) ? topicRaw : 'other';

  const { RESEND_API_KEY, CONTACT_TO, CONTACT_FROM } = env;
  if (!RESEND_API_KEY || !CONTACT_TO || !CONTACT_FROM) {
    console.error('contact: email environment variables are not configured');
    return problem(
      'The contact form is not finished being set up. Please email us directly in the meantime.',
      500
    );
  }

  const text = [
    `Name:         ${name}`,
    `Email:        ${email}`,
    `Organization: ${organization || '—'}`,
    `Topic:        ${topic}`,
    '',
    message,
  ].join('\n');

  const res = await fetch('https://api.resend.com/emails', {
    method: 'POST',
    headers: {
      authorization: `Bearer ${RESEND_API_KEY}`,
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      from: CONTACT_FROM,
      to: [CONTACT_TO],
      reply_to: email,
      subject: `Website enquiry (${topic}) — ${name}`,
      text,
    }),
  });

  if (!res.ok) {
    console.error('contact: delivery failed', res.status, await res.text());
    return problem('We could not deliver that message. Please try again, or email us directly.', 502);
  }

  return Response.redirect(new URL('/contact/thanks/', request.url).href, 303);
};
