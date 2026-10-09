import { Nav } from "../components/Nav";

export const metadata = {
  title: "Privacy",
  description: "What DriftWatch stores today, what it will store later, and how to delete your data.",
  alternates: { canonical: "/privacy" },
  openGraph: {
    type: "website",
    url: "/privacy",
    title: "Privacy",
    description: "What DriftWatch stores today, what it will store later, and how to delete your data.",
    images: [{ url: "/og.png", width: 1200, height: 630 }],
  },
};

const h2 = "mt-8 text-xl font-semibold text-[var(--mk-fg)]";
const p = "mt-3 leading-7 text-[var(--mk-muted)]";
const ul = "mt-3 list-disc space-y-2 pl-6 leading-7 text-[var(--mk-muted)]";

export default function Privacy() {
  return (
    <>
      <Nav />
      <main className="mx-auto max-w-3xl px-4 py-12 text-[var(--mk-fg)] sm:px-6">
        <h1 className="text-3xl font-semibold">Privacy</h1>
        <p className={p}>Last updated: 2026-10-08</p>

        <h2 className={h2}>What we store today</h2>
        <ul className={ul}>
          <li>Your account: your email address and a hashed password, managed by Supabase Auth.</li>
          <li>Your projects (name only).</li>
          <li>Details of your API keys: we store only a one-way hash of each key, so we cannot show it again, plus its name, a short display prefix of the key (the first 13 characters, which cannot be used to send events), its creation time and last-use time.</li>
          <li>The scores and event details you send to a project.</li>
          <li>A security log of actions such as creating or revoking a key and deleting your account. The deletion entry is stored without your identity. Earlier log entries keep a random identifier that no longer links to you after you delete your account.</li>
        </ul>

        <h2 className={h2}>What we will store when the local agent ships</h2>
        <p className={p}>The local agent is not available yet. When it ships, it will send us the scores it computes, with small metadata such as which signal and when. Raw prompts and responses will stay on your machine.</p>

        <h2 className={h2}>How long we will keep scores</h2>
        <p className={p}>Raw scores will be kept for 30 days, then rolled up into hourly summaries.</p>

        <h2 className={h2}>The live demo</h2>
        <p className={p}>The shared demo sends the question you type through the demo server to an LLM provider. Do not type anything sensitive into it.</p>

        <h2 className={h2}>Bot check</h2>
        <p className={p}>The sign-in and sign-up forms may use Cloudflare Turnstile, a bot check. It processes limited browser data under Cloudflare&apos;s terms.</p>

        <h2 className={h2}>Cookies and analytics</h2>
        <p className={p}>The site sets only cookies needed for signing in (the session and a short-lived sign-in verifier). It sets no third-party analytics at launch.</p>

        <h2 className={h2}>Where</h2>
        <p className={p}>Supabase hosts the database and sign-in. Vercel hosts the website. Render hosts the demo API.</p>

        <h2 className={h2}>Deleting your data</h2>
        <p className={p}>See <a className="underline" href="/data-deletion">how to delete your data</a>.</p>

        <h2 className={h2}>Contact</h2>
        <p className={p}>
          Write to <a className="underline" href="mailto:singh.rajvardhan.it@gmail.com">singh.rajvardhan.it@gmail.com</a>.
          The same contact is in <a className="underline" href="/.well-known/security.txt">security.txt</a>.
        </p>
      </main>
    </>
  );
}
