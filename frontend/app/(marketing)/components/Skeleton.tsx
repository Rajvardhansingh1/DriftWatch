export function Skeleton({ label, className = "" }: { label: string; className?: string }) {
  return <div role="status" aria-label={label} className={`mk-skeleton ${className}`} />;
}
