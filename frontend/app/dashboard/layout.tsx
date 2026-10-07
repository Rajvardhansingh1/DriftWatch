import Link from "next/link";
import { redirect } from "next/navigation";
import { createServerSupabase } from "@/lib/supabase/server";

export const metadata = { robots: { index: false, follow: false } };
// Per-request render: the nonce CSP from middleware cannot ride on a prerendered page.
export const dynamic = "force-dynamic";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const supabase = await createServerSupabase();
  const { data } = (await supabase?.auth.getUser()) ?? { data: { user: null } };
  if (!data.user) redirect("/auth/sign-in"); // defense in depth; middleware already guards
  return (
    <div className="min-h-screen bg-bg text-text">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <nav aria-label="Console" className="flex items-center gap-5 text-sm">
            <Link href="/dashboard" className="font-mono font-semibold">DriftWatch</Link>
            <Link href="/dashboard" className="text-dim hover:text-text">Projects</Link>
            <Link href="/dashboard/settings" className="text-dim hover:text-text">Settings</Link>
          </nav>
          <div className="flex items-center gap-3 text-xs text-dim">
            <span>{data.user.email}</span>
            <form action="/auth/sign-out" method="post">
              <button className="rounded border border-line px-2.5 py-1 text-text hover:border-dim">Log out</button>
            </form>
          </div>
        </div>
      </header>
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">{children}</div>
    </div>
  );
}
