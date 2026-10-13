// Builds the local dashboard page into ../driftwatch_llm/dashboard_static/ (index.html + assets/app.js + assets/app.css).
// It is built at release time and is not committed. It shares SignalChart, SyncChip and the panel definitions with the
// website; nothing from Supabase is imported.
import { execFileSync } from "node:child_process";
import { cpSync, mkdirSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = process.argv[2] ? resolve(process.argv[2]) : resolve(root, "..", "driftwatch_llm", "dashboard_static");
const BUDGET_BYTES = 5 * 1024 * 1024;

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, "assets"), { recursive: true });

await build({
  entryPoints: [join(root, "local", "main.tsx")],
  outfile: join(out, "assets", "app.js"),
  bundle: true,
  minify: true,
  format: "iife",
  target: ["es2020"],
  jsx: "automatic",
  define: { "process.env.NODE_ENV": '"production"' },
  tsconfig: join(root, "tsconfig.json"),
  logLevel: "warning",
});

const tailwind = join(root, "node_modules", "tailwindcss", "lib", "cli.js");
execFileSync(
  process.execPath,
  [tailwind, "-c", join(root, "local", "tailwind.config.cjs"), "-i", join(root, "local", "local.css"), "-o", join(out, "assets", "app.css"), "--minify"],
  { cwd: root, stdio: "inherit" },
);
cpSync(join(root, "local", "index.html"), join(out, "index.html"));

let total = 0;
for (const f of ["index.html", "assets/app.js", "assets/app.css"]) total += statSync(join(out, f)).size;
console.log(`local dashboard built: ${(total / 1024).toFixed(0)} KB -> ${out}`);
if (total > BUDGET_BYTES) {
  console.error(`over the ${BUDGET_BYTES / 1024 / 1024} MB budget`);
  process.exit(1);
}
