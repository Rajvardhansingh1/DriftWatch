import Link from "next/link";
import { MobileMenu } from "./MobileMenu";

const LINKS = [
  { href: "/#how", label: "Try it" },
  { href: "/#faq", label: "FAQ" },
  { href: "/demo", label: "Demo" },
];

export function Nav() {
  return (
    <header className="sticky top-0 z-20 border-b border-[var(--mk-line)] bg-[var(--mk-bg)]/90 backdrop-blur">
      <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
        <Link href="/" className="font-[var(--font-plex-mono)] text-sm font-semibold">DriftWatch</Link>
        <div className="hidden items-center gap-6 text-sm sm:flex">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} className="text-[var(--mk-muted)] hover:text-[var(--mk-fg)]">{l.label}</Link>
          ))}
          <Link href="/auth/sign-in" className="text-[var(--mk-fg)]">Log in</Link>
          <Link href="/auth/sign-up" className="rounded bg-[var(--mk-accent)] px-3 py-1.5 font-medium text-[var(--mk-surface)]">Sign up</Link>
        </div>
        <MobileMenu links={LINKS} />
      </nav>
    </header>
  );
}
