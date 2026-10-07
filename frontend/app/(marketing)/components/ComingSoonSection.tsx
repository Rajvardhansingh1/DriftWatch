type Item = { title: string; text: string };

// The only place later scope appears. Renders nothing once everything has shipped.
export function ComingSoonSection({ items }: { items: Item[] }) {
  if (items.length === 0) return null;
  return (
    <section id="coming-soon" aria-labelledby="coming-soon-title" className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      <h2 id="coming-soon-title" className="text-2xl font-semibold">Coming soon</h2>
      <p className="mt-2 text-sm text-[var(--mk-muted)]">Planned next. Not available yet.</p>
      <ul className="mt-8 grid gap-4 md:grid-cols-2">
        {items.map((i) => (
          <li key={i.title} className="rounded-lg border border-dashed border-[var(--mk-line)] p-5">
            <h3 className="font-medium">{i.title}</h3>
            <p className="mt-2 text-sm text-[var(--mk-muted)]">{i.text}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
