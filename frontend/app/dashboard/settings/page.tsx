import { redirect } from "next/navigation";
import { AccountDanger } from "@/components/console/AccountDanger";
import { createServerSupabase } from "@/lib/supabase/server";

export default async function SettingsPage() {
  const supabase = await createServerSupabase();
  const { data } = (await supabase?.auth.getUser()) ?? { data: { user: null } };
  if (!data.user) redirect("/auth/sign-in");
  const email = data.user.email ?? "";
  return (
    <main>
      <h1 className="text-xl font-semibold">Settings</h1>
      <p className="mt-2 text-sm text-dim">Signed in as {email}</p>

      <section aria-labelledby="export" className="mt-8">
        <h2 id="export" className="text-sm font-semibold">Export your data</h2>
        <p className="mt-2 max-w-xl text-sm text-dim">
          Download your projects, key details (never the keys themselves), the latest 20,000 signal rows,
          hourly summaries and audit events as one JSON file.
        </p>
        <a
          href="/dashboard/settings/export"
          className="mt-3 inline-block rounded border border-line px-4 py-2 text-sm hover:border-dim"
        >
          Download export
        </a>
      </section>

      <section aria-label="Danger zone" className="mt-10">
        <AccountDanger email={email} />
      </section>
    </main>
  );
}
