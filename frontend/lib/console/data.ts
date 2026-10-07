import type { SupabaseClient } from "@supabase/supabase-js";
import { hourlyToSeries, rowsToSeries } from "./series";
import { rangeToSince, type Range } from "./validate";
import type { SignalSeries } from "@/lib/types";

export type ProjectRow = { id: string; name: string; created_at: string };
export type KeyRow = {
  id: string; name: string; prefix: string;
  created_at: string; last_used_at: string | null; revoked_at: string | null;
};

export async function listProjects(client: SupabaseClient): Promise<ProjectRow[]> {
  const { data, error } = await client.from("projects").select("id,name,created_at").order("created_at");
  if (error) throw new Error("projects unavailable");
  return (data ?? []) as ProjectRow[];
}

export async function getProject(client: SupabaseClient, id: string): Promise<ProjectRow | null> {
  const { data, error } = await client.from("projects").select("id,name,created_at").eq("id", id).maybeSingle();
  if (error) throw new Error("project unavailable");
  return (data as ProjectRow | null) ?? null;
}

export async function loadSeries(client: SupabaseClient, projectId: string, range: Range): Promise<SignalSeries> {
  const since = rangeToSince(range).toISOString();
  if (range === "30d") {
    const { data, error } = await client
      .from("signal_hourly")
      .select("signal,hour,avg_value")
      .eq("project_id", projectId)
      .gte("hour", since)
      .order("hour", { ascending: false })
      .limit(5000);
    if (error) throw new Error("series unavailable");
    return hourlyToSeries((data ?? []) as { signal: string; hour: string; avg_value: number }[]);
  }
  const { data, error } = await client
    .from("signal_records")
    .select("signal,value,occurred_at")
    .eq("project_id", projectId)
    .gte("occurred_at", since)
    .order("occurred_at", { ascending: false })
    .limit(3000);
  if (error) throw new Error("series unavailable");
  return rowsToSeries((data ?? []) as { signal: string; value: number; occurred_at: string }[]);
}

export async function listKeys(client: SupabaseClient, projectId: string): Promise<KeyRow[]> {
  const { data, error } = await client
    .from("project_api_keys")
    .select("id,name,prefix,created_at,last_used_at,revoked_at")
    .eq("project_id", projectId)
    .order("created_at", { ascending: false });
  if (error) throw new Error("keys unavailable");
  return (data ?? []) as KeyRow[];
}
