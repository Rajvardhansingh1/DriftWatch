import Link from "next/link";
import { type Feature, enabledFeatures, isLive } from "@/lib/features";
import { buildLd, serializeLd } from "@/lib/seo/jsonld";
import { ComingSoonSection } from "./components/ComingSoonSection";
import { HeroVisual } from "./components/HeroVisual";
import { LiveDemoTeaser } from "./components/LiveDemoTeaser";
import { Nav } from "./components/Nav";
import { FAQ, HERO, HOW_TO_STEPS, KEYS, MODES, ROADMAP, SIGNALS } from "./content";

export default function LandingPage() {
  const on = enabledFeatures();
  const siteUrl = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";
  const live = <T extends { needs?: Feature[] }>(xs: T[]) => xs.filter((x) => isLive(x, on));
  const cliLive = HOW_TO_STEPS.every((s) => isLive(s, on));
  const modes = live(MODES);
  const keys = live(KEYS);
  const upcoming = ROADMAP.filter((r) => !isLive(r, on));

  return (
    <>
      <Nav />
      <main>
        <section className="mx-auto grid max-w-6xl gap-10 px-4 pb-16 pt-14 sm:px-6 md:grid-cols-[1.1fr_0.9fr] md:pt-24">
          <div>
            <h1 className="text-4xl font-semibold leading-tight sm:text-5xl">{HERO.title}</h1>
            <p className="mt-5 max-w-xl text-lg text-[var(--mk-muted)]">{HERO.body}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href={HERO.primary.href} className="rounded bg-[var(--mk-accent)] px-4 py-2.5 font-medium text-[var(--mk-surface)]">{HERO.primary.label}</Link>
              <Link href={HERO.secondary.href} className="rounded border border-[var(--mk-line)] px-4 py-2.5">{HERO.secondary.label}</Link>
            </div>
          </div>
          <div className="aspect-square w-full max-w-md md:justify-self-end">
            <HeroVisual />
          </div>
        </section>

        <section aria-labelledby="signals" className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <h2 id="signals" className="text-2xl font-semibold">What does DriftWatch measure?</h2>
          <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {SIGNALS.map((s) => (
              <li key={s.name} className="mk-tilt rounded-lg border border-[var(--mk-line)] bg-[var(--mk-surface)] p-5">
                <h3 className="font-medium">{s.name}</h3>
                <p className="mt-2 text-sm text-[var(--mk-muted)]">{s.text}</p>
              </li>
            ))}
          </ul>
        </section>

        <section id="how" aria-labelledby="try-title" className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <h2 id="try-title" className="mb-6 text-2xl font-semibold">How can I try it right now?</h2>
          <p className="mb-6 max-w-2xl text-[var(--mk-muted)]">
            Open the live demo, push the bot into drift with one of the scenarios, and watch the signals react.
            Create an account to keep your place for what ships next.
          </p>
          <LiveDemoTeaser />
        </section>

        {cliLive && (
          <section aria-labelledby="start-title" className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
            <h2 id="start-title" className="text-2xl font-semibold">How do I monitor my own app?</h2>
            <ol className="mt-8 grid gap-4 md:grid-cols-3">
              {HOW_TO_STEPS.map((s, i) => (
                <li key={s.name} className="rounded-lg border border-[var(--mk-line)] bg-[var(--mk-surface)] p-5">
                  <p className="font-[var(--font-plex-mono)] text-xs text-[var(--mk-muted)]">Step {i + 1}</p>
                  <h3 className="mt-1 font-medium">{s.name}</h3>
                  <code className="mt-3 block rounded bg-black/80 px-3 py-2 font-[var(--font-plex-mono)] text-sm text-white">{s.command}</code>
                  <p className="mt-3 text-sm text-[var(--mk-muted)]">{s.text}</p>
                </li>
              ))}
            </ol>
          </section>
        )}

        {modes.length > 0 && (
          <section aria-labelledby="modes" className="mx-auto grid max-w-6xl gap-4 px-4 py-16 sm:px-6 md:grid-cols-2">
            <h2 id="modes" className="text-2xl font-semibold md:col-span-2">Local or web: where should I watch it?</h2>
            {modes.map((m) => (
              <div key={m.title} className="rounded-lg border border-[var(--mk-line)] p-5">
                <h3 className="font-medium">{m.title}</h3>
                <p className="mt-2 text-sm text-[var(--mk-muted)]">{m.text}</p>
              </div>
            ))}
          </section>
        )}

        {keys.length > 0 && (
          <section aria-labelledby="keys" className="mx-auto grid max-w-6xl gap-4 px-4 py-16 sm:px-6 md:grid-cols-2">
            <h2 id="keys" className="text-2xl font-semibold md:col-span-2">What happens to my API keys?</h2>
            {keys.map((k) => (
              <div key={k.title} className="rounded-lg border border-[var(--mk-line)] p-5">
                <h3 className="font-medium">{k.title}</h3>
                <p className="mt-2 text-sm text-[var(--mk-muted)]">{k.text}</p>
              </div>
            ))}
          </section>
        )}

        <ComingSoonSection items={upcoming} />

        <section id="faq" aria-labelledby="faq-title" className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
          <h2 id="faq-title" className="text-2xl font-semibold">Questions</h2>
          <div className="mt-6 divide-y divide-[var(--mk-line)]">
            {live(FAQ).map((f) => (
              <details key={f.question} className="py-4">
                <summary className="cursor-pointer font-medium">{f.question}</summary>
                <p className="mt-3 text-[var(--mk-muted)]">{f.answer}</p>
              </details>
            ))}
          </div>
        </section>
      </main>

      <footer className="border-t border-[var(--mk-line)]">
        <div className="mx-auto flex max-w-6xl flex-wrap gap-6 px-4 py-8 text-sm text-[var(--mk-muted)] sm:px-6">
          <span>DriftWatch</span>
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
          <Link href="/data-deletion">Delete your data</Link>
          <a href="/.well-known/security.txt">Security</a>
        </div>
      </footer>

      {buildLd(on, siteUrl).map((d, i) => (
        <script key={i} type="application/ld+json" dangerouslySetInnerHTML={{ __html: serializeLd(d) }} />
      ))}
    </>
  );
}
