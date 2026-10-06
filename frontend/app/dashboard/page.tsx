import { createServerSupabase } from "@/lib/supabase/server";

export const metadata = { robots: { index: false, follow: false } };
// Per-request render: the nonce CSP from middleware cannot ride on a prerendered page.
export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  const supabase = await createServerSupabase();
  const { data } = (await supabase?.auth.getUser()) ?? { data: { user: null } };
  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="text-lg font-semibold">Your projects</h1>
      <p className="mt-2 text-sm text-neutral-400">Signed in as {data.user?.email}</p>
      <form action="/auth/sign-out" method="post" className="mt-6">
        <button className="rounded border border-neutral-600 px-3 py-1.5 text-sm">Log out</button>
      </form>
    </main>
  );
}
