// announce=false hides it from assistive tech when a parent live region already announces state.
export function Skeleton({ label, className = "", announce = true }: { label: string; className?: string; announce?: boolean }) {
  return announce
    ? <div role="status" aria-label={label} className={`mk-skeleton ${className}`} />
    : <div aria-hidden="true" className={`mk-skeleton ${className}`} />;
}
