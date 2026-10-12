import { redirect } from "next/navigation";
import { DeviceApprove } from "@/components/console/DeviceApprove";
import { listProjects, type ProjectRow } from "@/lib/console/data";
import { formatUserCode, normalizeUserCode } from "@/lib/console/device";
import { createServerSupabase } from "@/lib/supabase/server";

export const metadata = { title: "Approve CLI sign-in", robots: { index: false, follow: false } };
// Per-request render: the nonce CSP from middleware cannot ride on a prerendered page.
export const dynamic = "force-dynamic";

export default async function DevicePage({
  searchParams,
}: {
  searchParams: Promise<{ code?: string | string[] }>;
}) {
  const supabase = await createServerSupabase();
  if (!supabase) redirect("/auth/sign-in");
  const { data } = await supabase.auth.getUser(); // server-validated, never getSession()
  if (!data.user) redirect("/auth/sign-in"); // defense in depth; middleware already guards

  const sp = await searchParams;
  const raw = Array.isArray(sp.code) ? sp.code[0] : sp.code;
  const normalized = normalizeUserCode(raw);

  let projects: ProjectRow[] = [];
  let projectsError = false;
  try {
    projects = await listProjects(supabase);
  } catch {
    projectsError = true;
  }

  return (
    <main className="mx-auto max-w-lg p-6">
      <h1 className="text-xl font-semibold">Approve a CLI sign-in</h1>
      <p className="mt-2 text-sm text-dim">
        You signed in as {data.user.email}. A command-line tool is asking to send drift scores to one of your projects.
      </p>
      <div className="mt-6">
        <DeviceApprove
          initialCode={normalized ? formatUserCode(normalized) : ""}
          projects={projects.map((p) => ({ id: p.id, name: p.name }))}
          projectsError={projectsError}
        />
      </div>
    </main>
  );
}
