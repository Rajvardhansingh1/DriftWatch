import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { KeyManager } from "@/components/console/KeyManager";
import { getProject, listKeys } from "@/lib/console/data";
import { isUuid } from "@/lib/console/validate";
import { createServerSupabase } from "@/lib/supabase/server";

export default async function KeysPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  if (!isUuid(projectId)) notFound();
  const supabase = await createServerSupabase();
  if (!supabase) redirect("/auth/sign-in");
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) redirect("/auth/sign-in");
  const project = await getProject(supabase, projectId);
  if (!project) notFound();
  const keys = await listKeys(supabase, projectId); // admins only (RLS); others get an empty list
  return (
    <main>
      <p className="text-xs text-dim">
        <Link href="/dashboard" className="hover:text-text">Projects</Link> /{" "}
        <Link href={`/dashboard/${projectId}`} className="hover:text-text">{project.name}</Link> / API keys
      </p>
      <h1 className="mt-2 text-xl font-semibold">API keys</h1>
      <p className="mt-2 max-w-2xl text-sm text-dim">
        A key can only send events to this project. It cannot read any data, so a leaked key can be
        revoked without exposing your scores.
      </p>
      <div className="mt-6">
        <KeyManager
          projectId={projectId}
          keys={keys}
          apiBase={process.env.NEXT_PUBLIC_SUPABASE_URL ?? ""}
          anonKey={process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? ""}
        />
      </div>
    </main>
  );
}
