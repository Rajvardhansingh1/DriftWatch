// DEV-ONLY: builds the local dashboard, serves it from a real agent runtime (e2e/local_dashboard_demo.py) and drives
// real Chrome through the sign-in and the page. Prints a PASS/FAIL table. See e2e/README.md.
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = resolve(fileURLToPath(import.meta.url), "../..");
const PLAYWRIGHT_CORE_DIR = process.env.PLAYWRIGHT_CORE_DIR;
if (!PLAYWRIGHT_CORE_DIR) {
  console.error("PLAYWRIGHT_CORE_DIR is not set (see e2e/README.md).");
  process.exit(2);
}
const CHROME = process.env.CHROME_PATH ?? "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PYTHON = process.env.PYTHON ?? "python";
const { chromium } = createRequire(join(PLAYWRIGHT_CORE_DIR, "package.json"))("playwright-core");

const results = [];
async function check(name, fn) {
  try {
    const detail = await fn();
    results.push(["PASS", name, detail ?? ""]);
  } catch (e) {
    results.push(["FAIL", name, String(e.message ?? e).split("\n")[0]]);
  }
}
const ok = (cond, msg) => {
  if (!cond) throw new Error(msg);
};

const out = mkdtempSync(join(tmpdir(), "dw_local_static_"));
const build = spawnSync(process.execPath, [join(FRONTEND, "scripts", "build-local.mjs"), out], { stdio: "inherit" });
if (build.status !== 0) process.exit(1);

const demo = spawn(PYTHON, [join(FRONTEND, "e2e", "local_dashboard_demo.py"), out], { stdio: ["pipe", "pipe", "inherit"] });
const info = await new Promise((resolveInfo, reject) => {
  let buf = "";
  demo.stdout.on("data", (d) => {
    buf += d;
    if (buf.includes("\n")) resolveInfo(JSON.parse(buf.split("\n")[0]));
  });
  demo.on("exit", (c) => reject(new Error(`demo exited early (${c})`)));
  setTimeout(() => reject(new Error("demo did not start")), 120000);
});
const BASE = `http://127.0.0.1:${info.port}`;

const browser = await chromium.launch({ executablePath: CHROME, headless: true });
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  const requests = [];
  const consoleErrors = [];
  page.on("request", (r) => requests.push(r.url()));
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(String(e)));

  await check("without a token the page explains how to open it and shows no data", async () => {
    await page.goto(BASE + "/");
    await page.waitForSelector("text=driftwatch dashboard");
    ok(!(await page.content()).includes("embedding drift"), "data shown without a session");
    consoleErrors.length = 0; // the browser logs the expected 401 of the sign-in probe
  });

  await check("the link signs in, removes the token from the address bar and shows charts", async () => {
    await page.goto(`${BASE}/#token=${info.token}`);
    await page.waitForSelector("text=embedding drift", { timeout: 15000 });
    ok(!page.url().includes("token"), `token still in the URL: ${page.url()}`);
    ok((await page.locator("svg path.recharts-line-curve").count()) >= 1, "no chart line drawn");
  });

  await check("the session cookie is HttpOnly and SameSite=Strict, and not readable by scripts", async () => {
    const cookie = (await context.cookies(BASE)).find((c) => c.name === "dw_session");
    ok(cookie && cookie.httpOnly && cookie.sameSite === "Strict", JSON.stringify(cookie));
    ok(!(await page.evaluate(() => document.cookie)).includes("dw_session"), "cookie visible to script");
  });

  await check("the sync chip and notices read sensibly (no key yet: events are pending)", async () => {
    const text = await page.locator("[role=status]").first().innerText();
    ok(/pending/i.test(text), text);
  });

  await check("changing the range reloads without errors", async () => {
    await page.getByRole("button", { name: "1h" }).click();
    await page.waitForTimeout(800);
    await page.getByRole("button", { name: "7d" }).click();
    await page.waitForSelector("text=embedding drift");
  });

  await check("the page makes no request to any other host", async () => {
    const foreign = requests.filter((u) => !u.startsWith(BASE) && !u.startsWith("data:"));
    ok(foreign.length === 0, foreign.join(", "));
  });

  await check("a script on another origin cannot read the API (no CORS) even though a cookie exists", async () => {
    const other = await context.newPage();
    await other.goto("http://localhost:" + info.port + "/"); // a different origin from 127.0.0.1
    const verdict = await other.evaluate(async (base) => {
      try {
        const r = await fetch(base + "/api/projects", { credentials: "include" });
        return "got " + r.status;
      } catch {
        return "blocked";
      }
    }, BASE);
    ok(verdict === "blocked", verdict);
    await other.close();
  });

  await check("a foreign Host header is refused", async () => {
    const r = await fetch(BASE + "/", { headers: { Host: "evil.example.com" } }).catch(() => null);
    // Node's fetch forbids overriding Host; use a raw request instead
    const status = await new Promise((res) => {
      import("node:http").then(({ request }) => {
        const req = request({ host: "127.0.0.1", port: info.port, path: "/", headers: { Host: "evil.example.com" } }, (resp) => {
          resp.resume();
          res(resp.statusCode);
        });
        req.end();
      });
    });
    ok(status === 403, `status ${status}`);
  });

  await check("no console errors", async () => {
    ok(consoleErrors.length === 0, consoleErrors.slice(0, 3).join(" | "));
  });

  await page.screenshot({ path: join(out, "local-dashboard.png"), fullPage: true });
  console.log("screenshot:", join(out, "local-dashboard.png"));
} finally {
  await browser.close();
  demo.stdin.end();
}

console.log("\nLocal dashboard browser check");
for (const [kind, name, detail] of results) console.log(`${kind}  ${name}${detail ? ` -- ${detail}` : ""}`);
const failed = results.filter(([k]) => k === "FAIL").length;
console.log(`\n${results.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
