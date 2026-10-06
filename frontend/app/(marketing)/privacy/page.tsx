import { Nav } from "../components/Nav";

export const metadata = {
  title: "Privacy",
  alternates: { canonical: "/privacy" },
  openGraph: { url: "/privacy" },
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
        <p className={p}>Last updated: 2026-10-07</p>

        <h2 className={h2}>What we store today</h2>
        <ul className={ul}>
          <li>Your account: your email address and a hashed password, managed by Supabase Auth.</li>
        </ul>

        <h2 className={h2}>What we will store when you use projects and the local agent</h2>
        <p className={p}>These features are not live yet. When they ship, this is how they will work. When you use projects and the local agent, we also store:</p>
        <ul className={ul}>
          <li>Your projects and the scores DriftWatch computes for them, with small metadata such as which signal and when.</li>
          <li>Hashes of your project API keys. We cannot show a key again after you create it.</li>
          <li>An audit log of security actions, such as creating or revoking a key.</li>
        </ul>
        <p className={p}>Raw prompts and responses stay on your machine. Only scores and small metadata are sent to us.</p>

        <h2 className={h2}>How long we will keep scores</h2>
        <p className={p}>Raw scores will be kept for 30 days, then rolled up into hourly summaries.</p>

        <h2 className={h2}>The live demo</h2>
        <p className={p}>The shared demo sends the question you type through the demo server to an LLM provider. Do not type anything sensitive into it.</p>

        <h2 className={h2}>Bot check</h2>
        <p className={p}>The sign-in and sign-up forms may use Cloudflare Turnstile, a bot check. It processes limited browser data under Cloudflare&apos;s terms.</p>

        <h2 className={h2}>Cookies and analytics</h2>
        <p className={p}>The only cookie is the session cookie used to keep you signed in. The site sets no third-party analytics at launch.</p>

        <h2 className={h2}>Where</h2>
        <p className={p}>Supabase hosts the database and sign-in. Vercel hosts the website. Render hosts the demo API.</p>

        <h2 className={h2}>Deleting your data</h2>
        <p className={p}>See <a className="underline" href="/data-deletion">how to delete your data</a>.</p>

        <h2 className={h2}>Contact</h2>
        <p className={p}>Use the contact in <a className="underline" href="/.well-known/security.txt">security.txt</a>.</p>
      </main>
    </>
  );
}
