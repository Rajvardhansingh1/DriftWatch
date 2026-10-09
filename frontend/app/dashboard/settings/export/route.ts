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
  const body = JSON.stringify(data);
  // Serverless responses cap near 4.5 MB; refuse cleanly instead of failing mid-download.
  if (new TextEncoder().encode(body).length > 4_000_000) {
    return new Response("Export too large. Contact us and we will send it to you.", {
      status: 413,
      headers: { "Content-Type": "text/plain", "Cache-Control": "no-store" },
    });
  }
  return new Response(body, {
    headers: {
      "Content-Type": "application/json",
      "Content-Disposition": 'attachment; filename="driftwatch-export.json"',
      "Cache-Control": "no-store",
    },
  });
}
