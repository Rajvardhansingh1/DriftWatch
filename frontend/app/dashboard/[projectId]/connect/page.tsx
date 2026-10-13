import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { ConnectManager, type ConnectedModel } from "@/components/console/ConnectManager";
import type { ProbeInput } from "@/lib/connect/core";
import { runStatus } from "@/lib/connect/core";
import { getProject } from "@/lib/console/data";
import { isUuid } from "@/lib/console/validate";
import { enabledFeatures } from "@/lib/features";
import { createServerSupabase } from "@/lib/supabase/server";

export default async function ConnectPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  if (!isUuid(projectId) || !enabledFeatures().has("cloudConnect")) notFound(); // dark until the owner flips the flag
  const supabase = await createServerSupabase();
  if (!supabase) redirect("/auth/sign-in");
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) redirect("/auth/sign-in");
  const project = await getProject(supabase, projectId);
  if (!project) notFound();
  // Row-level security decides what is visible: the table has no secret columns at all.
  const [{ data: model }, { data: probes }] = await Promise.all([
    supabase
      .from("connected_models")
      .select("provider,model,last4,interval_minutes,monthly_budget,enabled,calls_this_month,last_run_at,last_error")
      .eq("project_id", projectId)
      .maybeSingle(),
    supabase.from("connected_probes").select("prompt,expected,match_type,position").eq("project_id", projectId).order("position"),
  ]);
  const connected = (model as ConnectedModel | null) ?? null;
  const status = connected ? runStatus(connected, Date.now()) : "waiting";
  return (
    <main>
      <p className="text-xs text-dim">
        <Link href="/dashboard" className="hover:text-text">Projects</Link> /{" "}
        <Link href={`/dashboard/${projectId}`} className="hover:text-text">{project.name}</Link> / Connect a model
      </p>
      <h1 className="mt-2 text-xl font-semibold">Connect a model</h1>
      <div className="mt-6 max-w-2xl">
        <ConnectManager
          projectId={projectId}
          model={connected}
          probes={((probes ?? []) as (ProbeInput & { position: number })[]).map(({ prompt, expected, match_type }) => ({ prompt, expected, match_type }))}
          status={status}
          canEdit // every button is enforced again in the database: only a project admin can change anything
        />
      </div>
    </main>
  );
}
