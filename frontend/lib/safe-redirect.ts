// Only same-site relative paths. Blocks open redirects such as
// "https://evil", "//evil", "/\evil" (browsers treat "/\" like "//") and
// "/<tab>/evil" (the URL parser strips tab/CR/LF, collapsing it to "//evil").
export function safeNextPath(next: string | null | undefined, fallback = "/dashboard"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return fallback;
  }
  if (/[\x00-\x1F\x7F\\]/.test(next)) return fallback;
  const base = "http://x.invalid";
  const u = new URL(next, base);
  if (u.origin !== base) return fallback;
  return u.pathname + u.search + u.hash;
}
