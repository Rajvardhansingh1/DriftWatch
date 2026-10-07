import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

// Browser-side Supabase client. Uses only the anon/publishable key - the
// service-role key must never appear here (Spec_Upgrade.md section 4.4).
// Cookie-backed session so the server middleware can validate it. null when
// cloud auth isn't configured, so local-only mode keeps working.
let client: SupabaseClient | null = null;

export function getSupabaseClient(): SupabaseClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) return null;
  if (!client) client = createBrowserClient(url, anonKey);
  return client;
}

export function isCloudAuthConfigured(): boolean {
  return getSupabaseClient() !== null;
}
