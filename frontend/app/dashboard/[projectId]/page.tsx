import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { ProjectLive } from "@/components/console/ProjectLive";
import { getProject, loadSeries } from "@/lib/console/data";
import { isUuid, parseRange, RANGES } from "@/lib/console/validate";
import { createServerSupabase } from "@/lib/supabase/server";

export default async function ProjectPage({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ range?: string }>;
}) {
  const { projectId } = await params;
  const range = parseRange((await searchParams).range);
  if (!isUuid(projectId)) notFound();
  const supabase = await createServerSupabase();
  if (!supabase) redirect("/auth/sign-in");
  // Row-level security: someone else's project and a missing one look the same.
  const project = await getProject(supabase, projectId);
  if (!project) notFound();
  const initial = await loadSeries(supabase, projectId, range);
  return (
    <main>
      <p className="text-xs text-dim"><Link href="/dashboard" className="hover:text-text">Projects</Link> / {project.name}</p>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">{project.name}</h1>
        <div className="flex items-center gap-4 text-sm">
          <nav aria-label="Range" className="flex gap-2">
            {RANGES.map((r) => (
              <Link
                key={r}
                href={`/dashboard/${projectId}?range=${r}`}
                aria-current={r === range ? "page" : undefined}
                className={r === range ? "text-text underline" : "text-dim hover:text-text"}
              >
                {r}
              </Link>
            ))}
          </nav>
          <Link href={`/dashboard/${projectId}/keys`} className="rounded border border-line px-3 py-1.5 hover:border-dim">API keys</Link>
        </div>
      </div>
      <div className="mt-6">
        <ProjectLive projectId={projectId} range={range} initial={initial} />
      </div>
    </main>
  );
}
