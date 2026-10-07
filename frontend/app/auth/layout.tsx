// Nonce-based CSP needs a per-request render: a prerendered page cannot carry
// the nonce, and its scripts would be blocked.
export const dynamic = "force-dynamic";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
