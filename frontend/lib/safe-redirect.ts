// Only same-site relative paths. Blocks open redirects such as
// "https://evil", "//evil" and "/\evil" (browsers treat "/\" like "//").
export function safeNextPath(next: string | null | undefined, fallback = "/dashboard"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return fallback;
  }
  return next;
}
