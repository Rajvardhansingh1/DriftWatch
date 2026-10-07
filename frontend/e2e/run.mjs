// DEV-ONLY: builds the console against the local fake Supabase, drives real Chrome
// through the signed-in flows and prints a PASS/FAIL table. See e2e/README.md.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { DEMO_PROJECT_ID, TOKEN, USER, startFake, state } from "./fake-supabase.mjs";

const FRONTEND = resolve(fileURLToPath(import.meta.url), "../..");
const SHOTS = resolve(FRONTEND, "../.superpowers/sdd/2026-10-07-plan-2-cloud-console/shots");
const PLAYWRIGHT_CORE_DIR = process.env.PLAYWRIGHT_CORE_DIR
  ?? "C:/Users/RAJVAE~1/AppData/Local/Temp/claude/d--Work-ext-AIProjects/0d3dd6b8-8c9d-462c-b0d1-2ad9e773e31a/scratchpad/live";
const CHROME = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const HOST = "127.0.0.1";
const WEB = `http://${HOST}:3100`;
const SUPABASE_URL = `http://${HOST}:54321`;

const { chromium } = createRequire(join(PLAYWRIGHT_CORE_DIR, "package.json"))("playwright-core");

const env = {
  ...process.env,
  NEXT_PUBLIC_SUPABASE_URL: SUPABASE_URL,
  NEXT_PUBLIC_SUPABASE_ANON_KEY: "dummy-anon-key",
  NEXT_PUBLIC_SITE_URL: WEB,
  NEXT_PUBLIC_MONITOR_API_URL: `http://${HOST}:8000`,
  NEXT_TELEMETRY_DISABLED: "1",
};

// Same derivation as supabase-js (`sb-${hostname.split(".")[0]}-auth-token`) and the
// @supabase/ssr cookie format ("base64-" + base64url(JSON)); short enough for one chunk.
const COOKIE_NAME = `sb-${new URL(SUPABASE_URL).hostname.split(".")[0]}-auth-token`;
const session = {
  access_token: TOKEN, refresh_token: "fake-refresh", token_type: "bearer", expires_in: 3600,
  expires_at: Math.floor(Date.now() / 1000) + 10 * 365 * 86400, user: USER,
};
const COOKIE = {
  name: COOKIE_NAME,
  value: "base64-" + Buffer.from(JSON.stringify(session)).toString("base64url"),
  domain: HOST, path: "/", sameSite: "Lax", httpOnly: false, secure: false,
};

const results = [];
let current = "setup";
const consoleLog = []; // { check, type, text, url }
async function check(name, fn) {
  current = name;
  try {
    const detail = await fn();
    results.push({ name, ok: true, detail: detail ?? "" });
  } catch (e) {
    results.push({ name, ok: false, detail: String(e?.message ?? e).split("\n")[0] });
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

function killTree(child) {
  if (!child || child.exitCode !== null) return;
  if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"], { stdio: "ignore" });
  else child.kill("SIGTERM");
}

async function waitFor(url, ms = 60_000) {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    try {
      await fetch(url, { redirect: "manual" });
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  throw new Error(`timed out waiting for ${url}`);
}

let next, fake, browser;
try {
  if (process.env.E2E_SKIP_BUILD !== "1") {
    console.log("building with the fake Supabase env...");
    const b = spawnSync("npm run build", { cwd: FRONTEND, env, stdio: "inherit", shell: true });
    if (b.status !== 0) throw new Error("next build failed");
  }
  fake = await startFake({ host: HOST, log: process.env.E2E_VERBOSE ? (l) => console.log("[fake]", l) : () => {} });
  next = spawn(process.execPath, [join(FRONTEND, "node_modules/next/dist/bin/next"), "start", "-p", "3100", "-H", HOST], {
    cwd: FRONTEND, env, stdio: ["ignore", "pipe", "pipe"],
  });
  next.stdout.on("data", (d) => process.env.E2E_VERBOSE && process.stdout.write(`[next] ${d}`));
  next.stderr.on("data", (d) => process.stderr.write(`[next] ${d}`));
  await waitFor(`${WEB}/`);

  browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  // Surface CSP violations as console messages (init scripts are not subject to the page CSP).
  await context.addInitScript(() => {
    document.addEventListener("securitypolicyviolation", (e) =>
      console.error(`CSP-VIOLATION ${e.violatedDirective} blocked=${e.blockedURI}`));
  });
  await context.addCookies([COOKIE]);
  const page = await context.newPage();
  const pageErrors = [];
  page.on("console", (m) => consoleLog.push({ check: current, type: m.type(), text: m.text(), url: m.location()?.url ?? "" }));
  page.on("pageerror", (e) => pageErrors.push({ check: current, text: String(e?.message ?? e) }));
  rmSync(SHOTS, { recursive: true, force: true }); // no stale shots passing check k
  mkdirSync(SHOTS, { recursive: true });

  let secondId = "";
  let apiKey = "";
  const leakSnapshots = [];
  const snapshotLeak = async (when) => {
    const s = await page.evaluate(() => ({
      cookie: document.cookie,
      local: JSON.stringify({ ...localStorage }),
      session: JSON.stringify({ ...sessionStorage }),
      href: location.href,
    }));
    const jar = JSON.stringify(await context.cookies());
    leakSnapshots.push({ when, ...s, jar });
  };

  await check("a. /dashboard lists projects without redirect", async () => {
    const r = await page.goto(`${WEB}/dashboard`);
    assert(r.status() === 200, `status ${r.status()}`);
    assert(new URL(page.url()).pathname === "/dashboard", `landed on ${page.url()}`);
    await page.getByRole("heading", { name: "Your projects" }).waitFor({ timeout: 5000 });
    await page.getByText("Demo app").waitFor({ timeout: 5000 });
    return "Your projects + Demo app";
  });

  await check("b. create project 'Second' navigates to its page", async () => {
    await page.getByLabel("Project name").fill("Second");
    await page.getByRole("button", { name: "Create project" }).click();
    await page.waitForURL(/\/dashboard\/[0-9a-f-]{36}$/, { timeout: 10_000 });
    secondId = page.url().split("/").pop();
    assert(state.projects.some((p) => p.id === secondId && p.name === "Second"), "fake has no such project");
    await page.getByRole("heading", { name: "Second" }).waitFor({ timeout: 5000 });
    return `/dashboard/${secondId}`;
  });

  await check("c. project page renders charts and status chip, no page errors", async () => {
    const before = pageErrors.length;
    await page.goto(`${WEB}/dashboard/${DEMO_PROJECT_ID}`);
    await page.getByRole("heading", { name: "Demo app" }).waitFor({ timeout: 5000 });
    await page.getByText("combined drift score").waitFor({ timeout: 5000 });
    await page.waitForTimeout(3000); // let Realtime try and fail
    const svgs = await page.locator(".recharts-wrapper").count();
    assert(svgs >= 2, `only ${svgs} rendered charts (expected combined + embedding drift)`);
    const chip = (await page.getByRole("status").innerText()).trim();
    assert(["Live", "Connecting", "Offline"].includes(chip), `chip shows "${chip}"`);
    const errs = pageErrors.slice(before);
    assert(errs.length === 0, `page errors: ${errs.map((e) => e.text).join(" | ")}`);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: join(SHOTS, "project-mobile-390x844.png"), fullPage: true });
    await page.setViewportSize({ width: 1280, height: 900 });
    return `${svgs} charts drawn, chip "${chip}"`;
  });

  await check("d. range links change ?range= and re-render", async () => {
    const seen = [];
    for (const [r, expectChip] of [["7d", null], ["30d", "Paused"], ["24h", null]]) {
      await page.getByRole("navigation", { name: "Range" }).getByRole("link", { name: r, exact: true }).click();
      await page.waitForURL(new RegExp(`[?&]range=${r}$`), { timeout: 10_000 });
      const cur = page.getByRole("navigation", { name: "Range" }).locator('[aria-current="page"]');
      await page.waitForFunction((want) => document.querySelector('nav[aria-label="Range"] [aria-current="page"]')?.textContent === want, r, { timeout: 5000 });
      const chip = (await page.getByRole("status").innerText()).trim();
      if (expectChip) assert(chip === expectChip, `${r}: chip "${chip}", expected ${expectChip}`);
      const charts = await page.locator(".recharts-wrapper").count();
      assert(charts >= 2, `${r}: ${charts} charts`);
      seen.push(`${r}:${await cur.innerText()}/${chip}`);
    }
    return seen.join(" ");
  });

  await check("e. key shown once, hidden after save, never persisted client-side", async () => {
    await page.goto(`${WEB}/dashboard/${DEMO_PROJECT_ID}/keys`);
    await snapshotLeak("before create");
    assert((await page.getByText("Send a first event").count()) === 0, "example visible before any key");
    await page.getByLabel("Key name").fill("laptop");
    await page.getByRole("button", { name: "Create key" }).click();
    const code = page.getByRole("region", { name: "New API key" }).locator("code");
    await code.waitFor({ timeout: 10_000 });
    apiKey = (await code.innerText()).trim();
    assert(/^dw_[0-9a-f]{10}_[0-9a-f]{64}$/.test(apiKey), `bad key "${apiKey.slice(0, 16)}..."`);
    assert(await page.getByText("Send a first event").isVisible(), "example missing while key shown");
    await page.getByText("Send a first event").click();
    assert((await page.locator("pre").innerText()).includes(apiKey), "example lacks the key");
    await page.getByText("laptop").first().waitFor();
    await snapshotLeak("key displayed");
    await page.getByRole("button", { name: "I have saved it" }).click();
    await page.getByRole("region", { name: "New API key" }).waitFor({ state: "detached", timeout: 5000 });
    assert(!(await page.content()).includes(apiKey), "key still in DOM after save");
    assert((await page.getByText("Send a first event").count()) === 0, "example still visible after save");
    await snapshotLeak("after save");
    await page.reload();
    await page.getByRole("heading", { name: "API keys" }).waitFor();
    assert(!(await page.content()).includes(apiKey), "key in DOM after reload");
    assert((await page.getByText("Send a first event").count()) === 0, "example visible after reload");
    await page.getByText("laptop").first().waitFor();
    await snapshotLeak("after reload");
    for (const s of leakSnapshots) {
      for (const where of ["cookie", "local", "session", "href", "jar"]) {
        assert(!s[where].includes(apiKey), `key found in ${where} (${s.when})`);
      }
    }
    return `key ${apiKey.slice(0, 13)}... shown, hidden, absent after reload; ${leakSnapshots.length} storage snapshots clean`;
  });

  await check("f. revoke needs two clicks then shows revoked", async () => {
    const row = page.locator("li", { hasText: "laptop" });
    await row.getByRole("button", { name: "Revoke" }).click();
    await row.getByRole("button", { name: "Click again to revoke" }).waitFor({ timeout: 3000 });
    assert(state.project_api_keys.every((k) => !k.revoked_at), "revoked after one click");
    await row.getByRole("button", { name: "Click again to revoke" }).click();
    await row.getByText("revoked", { exact: true }).waitFor({ timeout: 10_000 });
    assert(state.project_api_keys[0].revoked_at, "fake not revoked");
    assert((await row.getByRole("button").count()) === 0, "revoke button still shown");
    await page.screenshot({ path: join(SHOTS, "keys-desktop.png"), fullPage: true });
    return "first click asks, second revokes";
  });

  await check("i. bad and unknown project ids give 404", async () => {
    const out = [];
    for (const id of ["not-a-uuid", "0e6f1c9a-3b2d-4f5e-8a7b-6c5d4e3f2a1b"]) {
      for (const suffix of ["", "/keys"]) {
        const r = await page.goto(`${WEB}/dashboard/${id}${suffix}`);
        assert(r.status() === 404, `${id}${suffix}: status ${r.status()}`);
        await page.getByText(/could not be found/i).waitFor({ timeout: 5000 });
        out.push(`${id.slice(0, 10)}${suffix}=404`);
      }
    }
    return out.join(" ");
  });

  await check("h. without the session cookie /dashboard redirects to sign-in", async () => {
    await context.clearCookies();
    await page.goto(`${WEB}/dashboard`);
    const { pathname: landed, origin } = new URL(page.url());
    await context.addCookies([COOKIE]);
    assert(landed === "/auth/sign-in", `landed on ${landed}`);
    return `${origin}${landed}`; // next start builds absolute redirects with its own hostname
  });

  await check("g1. export returns JSON without key_hash", async () => {
    await page.goto(`${WEB}/dashboard/settings`);
    await page.getByRole("heading", { name: "Settings" }).waitFor();
    await page.screenshot({ path: join(SHOTS, "settings-desktop.png"), fullPage: true });
    const href = await page.getByRole("link", { name: "Download export" }).getAttribute("href");
    const r = await page.request.get(new URL(href, WEB).href);
    assert(r.status() === 200, `status ${r.status()}`);
    assert((r.headers()["content-type"] ?? "").startsWith("application/json"), `type ${r.headers()["content-type"]}`);
    assert((r.headers()["content-disposition"] ?? "").includes("attachment"), "not an attachment");
    const text = await r.text();
    assert(!text.includes("key_hash"), "export contains key_hash");
    assert(!text.includes(apiKey.slice(14)), "export contains the key secret");
    const data = JSON.parse(text);
    assert(data.api_keys.length === 1 && data.projects.length === 2, `api_keys ${data.api_keys.length}, projects ${data.projects.length}`);
    return `${text.length} bytes, ${data.api_keys.length} key meta, ${data.signal_records_latest_20000.length} rows`;
  });

  await check("g2. delete needs the typed email, then leaves to /", async () => {
    const button = page.getByRole("button", { name: "Delete my account" });
    assert(await button.isDisabled(), "button enabled before typing");
    const input = page.getByLabel("Type your email to confirm");
    await input.fill("wrong@example.com");
    assert(await button.isEnabled(), "button still disabled after typing");
    await button.click();
    await page.getByText("Type your account email exactly to confirm.").waitFor({ timeout: 10_000 });
    assert(!state.deleted, "deleted with the wrong email");
    await input.fill("tester@example.com");
    await button.click();
    await page.waitForURL(`${WEB}/`, { timeout: 15_000 });
    assert(state.deleted, "fake account not deleted");
    assert(state.logouts >= 1, "no sign-out call");
    const r = await page.goto(`${WEB}/dashboard`);
    assert(new URL(page.url()).pathname === "/auth/sign-in", `after delete /dashboard -> ${page.url()} (${r.status()})`);
    return "disabled -> wrong email error -> deleted, at /, then /dashboard -> sign-in";
  });

  await check("k. screenshots saved (mobile project, desktop keys, desktop settings)", async () => {
    const files = ["project-mobile-390x844.png", "keys-desktop.png", "settings-desktop.png"];
    const missing = files.filter((f) => !existsSync(join(SHOTS, f)));
    assert(missing.length === 0, `missing ${missing.join(", ")}`);
    return files.join(", ");
  });

  current = "j";
  const ALLOWED = [
    // Realtime: the fake refuses websocket upgrades.
    (m) => /WebSocket connection to 'ws:\/\/127\.0\.0\.1:54321\/realtime\/v1\/websocket/.test(m.text),
    // Expected 404 documents in check i.
    (m) => m.check.startsWith("i.") && /status of 404/.test(m.text),
  ];
  await check("j. no CSP violations or unexpected console errors", async () => {
    const csp = consoleLog.filter((m) => /CSP-VIOLATION|Content Security Policy/i.test(m.text));
    assert(csp.length === 0, `CSP: ${csp.map((m) => m.text).join(" | ")}`);
    const bad = consoleLog.filter((m) => m.type === "error" && !ALLOWED.some((ok) => ok(m)));
    assert(bad.length === 0, `errors: ${bad.map((m) => m.text).join(" | ")}`);
    assert(pageErrors.length === 0, `page errors: ${pageErrors.map((e) => e.text).join(" | ")}`);
    return `${consoleLog.length} console messages, ${consoleLog.filter((m) => m.type === "error").length} allowed errors`;
  });
} catch (e) {
  results.push({ name: `harness (${current})`, ok: false, detail: String(e?.stack ?? e) });
} finally {
  await browser?.close().catch(() => {});
  killTree(next);
  fake?.close();
}

console.log("\nConsole messages observed:");
for (const m of consoleLog) console.log(`  [${m.check.split(".")[0]}] ${m.type}: ${m.text}${m.url ? ` (${m.url})` : ""}`);
console.log(`\nScreenshots: ${SHOTS}`);
console.log("\nRESULT  CHECK");
for (const r of results) console.log(`${r.ok ? "PASS  " : "FAIL  "}  ${r.name}${r.detail ? ` -- ${r.detail}` : ""}`);
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed ? 1 : 0);
