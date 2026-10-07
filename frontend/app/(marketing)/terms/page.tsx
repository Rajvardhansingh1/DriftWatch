import { Nav } from "../components/Nav";

export const metadata = {
  title: "Terms",
  description: "The terms for using the DriftWatch website and live demo.",
  alternates: { canonical: "/terms" },
  openGraph: {
    type: "website",
    url: "/terms",
    title: "Terms",
    description: "The terms for using the DriftWatch website and live demo.",
    images: [{ url: "/og.png", width: 1200, height: 630 }],
  },
};

const p = "mt-3 leading-7 text-[var(--mk-muted)]";

export default function Terms() {
  return (
    <>
      <Nav />
      <main className="mx-auto max-w-3xl px-4 py-12 text-[var(--mk-fg)] sm:px-6">
        <h1 className="text-3xl font-semibold">Terms</h1>
        <p className={p}>Last updated: 2026-10-07</p>
        <ul className="mt-6 list-disc space-y-3 pl-6 leading-7 text-[var(--mk-muted)]">
          <li>DriftWatch is provided as is, without warranty. It flags statistical drift. It does not guarantee your model is correct.</li>
          <li>Do not use the demo, the API or any limits we set to send abusive content, to attack the service, or to get around those limits.</li>
          <li>If you add provider keys in future features, you are responsible for those keys and for the costs they incur.</li>
          <li>We may suspend accounts that abuse the service.</li>
          <li>We may change these terms. Changes will be announced on this page.</li>
        </ul>
      </main>
    </>
  );
}
