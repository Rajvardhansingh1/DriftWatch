"use client";

import Link from "next/link";
import { useRef, useState } from "react";

type Item = { href: string; label: string };

// Only the menu is a client component; Nav stays a server component.
export function MobileMenu({ links }: { links: Item[] }) {
  const ref = useRef<HTMLDetailsElement>(null);
  const [open, setOpen] = useState(false);
  const close = () => {
    ref.current?.removeAttribute("open");
    setOpen(false);
  };
  return (
    <details ref={ref} className="sm:hidden" onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary className="cursor-pointer list-none text-sm" aria-expanded={open}>Menu</summary>
      <div className="absolute right-4 mt-2 flex flex-col gap-3 rounded border border-[var(--mk-line)] bg-[var(--mk-surface)] p-4 text-sm">
        {links.map((l) => <Link key={l.href} href={l.href} onClick={close}>{l.label}</Link>)}
        <Link href="/auth/sign-in" onClick={close}>Log in</Link>
        <Link href="/auth/sign-up" onClick={close} className="font-medium text-[var(--mk-accent)]">Sign up</Link>
      </div>
    </details>
  );
}
