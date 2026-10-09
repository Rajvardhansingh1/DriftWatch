import Link from "next/link";
import { redirect } from "next/navigation";
import { CreateProjectForm } from "@/components/console/CreateProjectForm";
import { listProjects } from "@/lib/console/data";
import { createServerSupabase } from "@/lib/supabase/server";

export default async function DashboardPage() {
  const supabase = await createServerSupabase();
  if (!supabase) redirect("/auth/sign-in");
  const { data } = await supabase.auth.getUser();
  if (!data.user) redirect("/auth/sign-in");
  const projects = await listProjects(supabase);
  return (
    <main>
      <h1 className="text-xl font-semibold">Your projects</h1>
      {projects.length === 0 ? (
        <p className="mt-3 max-w-xl text-sm text-dim">
          A project is one monitored LLM app. Create one, make an API key for it, and send events
          to see its drift scores here.
        </p>
      ) : (
        <ul className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <li key={p.id}>
              <Link href={`/dashboard/${p.id}`} className="block rounded border border-line bg-panel p-4 hover:border-dim">
                <p className="font-medium">{p.name}</p>
                <p className="mt-1 text-xs text-dim">Created {new Date(p.created_at).toLocaleDateString("en-GB")}</p>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <section aria-labelledby="new-project" className="mt-10">
        <h2 id="new-project" className="text-sm font-semibold">New project</h2>
        <div className="mt-3"><CreateProjectForm /></div>
      </section>
    </main>
  );
}
