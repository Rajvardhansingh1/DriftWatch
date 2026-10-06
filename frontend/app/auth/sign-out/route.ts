import { NextResponse } from "next/server";
import { createServerSupabase } from "@/lib/supabase/server";

export async function POST(request: Request) {
  const supabase = await createServerSupabase();
  // scope "global" revokes every refresh token for this user, not just this browser.
  await supabase?.auth.signOut({ scope: "global" });
  return NextResponse.redirect(new URL("/", request.url), { status: 303 });
}
