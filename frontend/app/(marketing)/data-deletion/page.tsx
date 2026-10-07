import { Nav } from "../components/Nav";

export const metadata = {
  title: "Delete your data",
  description: "How to ask for your DriftWatch account and data to be deleted.",
  alternates: { canonical: "/data-deletion" },
  openGraph: {
    type: "website",
    url: "/data-deletion",
    title: "Delete your data",
    description: "How to ask for your DriftWatch account and data to be deleted.",
    images: [{ url: "/og.png", width: 1200, height: 630 }],
  },
};

const p = "mt-3 leading-7 text-[var(--mk-muted)]";

export default function DataDeletion() {
  return (
    <>
      <Nav />
      <main className="mx-auto max-w-3xl px-4 py-12 text-[var(--mk-fg)] sm:px-6">
        <h1 className="text-3xl font-semibold">Delete your data</h1>
        <p className={p}>Last updated: 2026-10-07</p>
        <p className={p}>
          To delete your account and data today, contact the maintainer using the contact listed on the{" "}
          <a className="underline" href="/.well-known/security.txt">Security page</a> (/.well-known/security.txt).
        </p>
        <p className={p}>A self-serve option is planned.</p>
      </main>
    </>
  );
}
