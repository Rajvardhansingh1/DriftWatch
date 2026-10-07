import { createServerSupabase } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const supabase = await createServerSupabase();
  const { data: auth } = (await supabase?.auth.getUser()) ?? { data: { user: null } };
  if (!supabase || !auth.user) {
    return new Response("Sign in required", { status: 401, headers: { "Cache-Control": "no-store" } });
  }
  // Security-invoker function: row-level security decides what is included.
  const { data, error } = await supabase.rpc("export_my_data");
  if (error) {
    return new Response("Export unavailable", { status: 502, headers: { "Cache-Control": "no-store" } });
  }
  return new Response(JSON.stringify(data, null, 2), {
    headers: {
      "Content-Type": "application/json",
      "Content-Disposition": 'attachment; filename="driftwatch-export.json"',
      "Cache-Control": "no-store",
    },
  });
}
