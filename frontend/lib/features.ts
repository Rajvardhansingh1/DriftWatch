export type Feature = "cli" | "freeKey" | "cloudConnect";
const ALL: Feature[] = ["cli", "freeKey", "cloudConnect"];

// NEXT_PUBLIC_FEATURES="cli,freeKey" switches features on as they ship. The site
// never presents an unlisted feature as available (R13).
export function enabledFeatures(raw = process.env.NEXT_PUBLIC_FEATURES ?? ""): Set<Feature> {
  const wanted = raw.split(",").map((s) => s.trim());
  return new Set(ALL.filter((f) => wanted.includes(f)));
}

export function isLive(item: { needs?: Feature[] }, on: Set<Feature>): boolean {
  return (item.needs ?? []).every((f) => on.has(f));
}
