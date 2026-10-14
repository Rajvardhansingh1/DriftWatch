// Runs `npm audit` and fails on any high or critical advisory that is not in deploy/audit-exceptions.json (and not expired).
//   node scripts/audit-check.mjs
// An exception needs a reason and an expiry date, so "documented" cannot quietly become "forgotten".
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FAIL_ON = new Set(["high", "critical"]);

/** Advisories (objects, not package-name strings) found anywhere in an `npm audit --json` report. */
export function advisories(report) {
  const out = new Map();
  for (const vuln of Object.values(report?.vulnerabilities ?? {})) {
    for (const via of vuln.via ?? []) {
      if (via && typeof via === "object" && via.url) out.set(via.url, { url: via.url, title: via.title, severity: via.severity, name: via.name });
    }
  }
  return [...out.values()];
}

/** The advisories that must fail the build: serious, and not covered by an unexpired exception. */
export function unaccepted(report, exceptions, now = new Date()) {
  const byUrl = new Map((exceptions ?? []).map((e) => [e.id, e]));
  return advisories(report).filter((a) => {
    if (!FAIL_ON.has(a.severity)) return false;
    const e = byUrl.get(a.url.split("/").pop());
    if (!e || !e.reason || !e.expires) return true;
    return new Date(e.expires) < now;
  });
}

function main() {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
  const exceptions = JSON.parse(readFileSync(resolve(root, "deploy", "audit-exceptions.json"), "utf8")).npm ?? [];
  const run = spawnSync("npm", ["audit", "--omit=dev", "--json"], { encoding: "utf8", shell: true, cwd: resolve(root, "frontend") });
  let report;
  try {
    report = JSON.parse(run.stdout);
  } catch {
    console.error("could not read the output of npm audit");
    return 2;
  }
  const bad = unaccepted(report, exceptions);
  const all = advisories(report);
  console.log(`${all.length} advisories, ${all.length - bad.length} accepted or below high, ${bad.length} to fix`);
  for (const a of bad) console.log(`  ${a.severity}  ${a.name}  ${a.title}  ${a.url}`);
  return bad.length ? 1 : 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exit(main());
