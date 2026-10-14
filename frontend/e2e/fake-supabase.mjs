// DEV-ONLY fake of the Supabase Auth + PostgREST subset the console uses.
// In-memory state, no auth beyond one fixed bearer token. Never imported by app code.
// Realtime (websocket) is deliberately not implemented: upgrade requests are dropped.
import { createServer } from "node:http";
import { randomBytes, randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";

export const TOKEN = "fake-token";
export const DEMO_PROJECT_ID = "11111111-2222-4333-8444-555555555555";
const ORG_ID = "99999999-8888-4777-8666-555555555555";

export const USER = {
  id: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
  aud: "authenticated",
  role: "authenticated",
  email: "tester@example.com",
  email_confirmed_at: "2026-01-01T00:00:00Z",
  app_metadata: {},
  user_metadata: {},
  created_at: "2026-01-01T00:00:00Z",
};

const hex = (bytes) => randomBytes(bytes).toString("hex");

function seed() {
  const now = Date.now();
  const signal_records = [];
  const signal_hourly = [];
  for (const [signal, base] of [["combined_score", 0.2], ["embedding_drift", 0.3]]) {
    for (let i = 0; i < 30; i++) {
      signal_records.push({
        id: randomUUID(), project_id: DEMO_PROJECT_ID, event_id: randomUUID(), source: "seed", signal,
        value: Number((base + 0.1 * Math.sin(i / 4)).toFixed(3)),
        occurred_at: new Date(now - (30 - i) * 115_000).toISOString(),
      });
    }
    for (let h = 0; h < 48; h++) {
      signal_hourly.push({
        project_id: DEMO_PROJECT_ID, signal,
        hour: new Date(now - (48 - h) * 3_600_000).toISOString(),
        avg_value: Number((base + 0.05 * Math.cos(h / 6)).toFixed(3)), n: 10,
      });
    }
  }
  return {
    deleted: false,
    logouts: 0,
    projects: [{ id: DEMO_PROJECT_ID, organization_id: ORG_ID, name: "Demo app", settings: {}, created_at: new Date(now - 86_400_000).toISOString() }],
    project_api_keys: [],
    connected_models: [], // cloud connect settings (no secret columns exist on this table)
    connected_probes: [],
    device_codes: [], // device-login requests (mirrors private.device_codes in 0009)
    device_wrong_codes: 0, // wrong-code attempts by the one fake user (lockout at 5)
    signal_records,
    signal_hourly,
  };
}

export const state = seed();

const ALLOWED_HEADERS = "apikey, authorization, content-type, prefer, x-client-info, accept-profile, content-profile, x-supabase-api-version, range";

function send(req, res, status, body, extra = {}) {
  const headers = { ...extra };
  if (req.headers.origin) {
    headers["Access-Control-Allow-Origin"] = req.headers.origin;
    headers["Access-Control-Allow-Credentials"] = "true";
    headers["Vary"] = "Origin";
  }
  if (body === undefined) {
    res.writeHead(status, headers).end();
  } else {
    headers["Content-Type"] = "application/json; charset=utf-8";
    res.writeHead(status, headers).end(JSON.stringify(body));
  }
}

const authed = (req) => !state.deleted && req.headers.authorization === `Bearer ${TOKEN}`;

// PostgREST filters: col=op.value for eq/neq/gt/gte/lt/lte/is.null.
function applyQuery(rows, params) {
  let out = rows;
  for (const [col, raw] of params) {
    if (["select", "order", "limit", "offset"].includes(col)) continue;
    const dot = raw.indexOf(".");
    const op = raw.slice(0, dot);
    const v = raw.slice(dot + 1);
    const cmp = (a) => (typeof a === "number" ? a - Number(v) : String(a).localeCompare(v));
    const isTime = (a) => typeof a === "string" && !Number.isNaN(Date.parse(a)) && !Number.isNaN(Date.parse(v));
    const order = (a) => (isTime(a) ? Date.parse(a) - Date.parse(v) : cmp(a));
    const tests = {
      eq: (a) => String(a) === v, neq: (a) => String(a) !== v,
      gt: (a) => order(a) > 0, gte: (a) => order(a) >= 0, lt: (a) => order(a) < 0, lte: (a) => order(a) <= 0,
      is: (a) => (v === "null" ? a === null || a === undefined : String(a) === v),
    };
    if (!tests[op]) throw new Error(`unsupported filter ${col}=${raw}`);
    out = out.filter((r) => tests[op](r[col]));
  }
  const order = params.get("order");
  if (order) {
    const [col, dir] = order.split(".");
    out = [...out].sort((a, b) => (a[col] < b[col] ? -1 : a[col] > b[col] ? 1 : 0) * (dir === "desc" ? -1 : 1));
  }
  const limit = params.get("limit");
  return limit ? out.slice(0, Number(limit)) : out;
}

const TABLES = ["projects", "signal_records", "signal_hourly", "project_api_keys", "connected_models", "connected_probes"];

function rpc(name, args) {
  switch (name) {
    case "create_project": {
      const nm = String(args.p_name ?? "").trim();
      if (nm.length < 1 || nm.length > 64) return [422, { code: "PT422", message: "project name must be 1 to 64 characters", details: null, hint: null }];
      if (state.projects.length >= 5) return [422, { code: "PT422", message: "project limit reached", details: null, hint: null }];
      const p = { id: randomUUID(), organization_id: ORG_ID, name: nm, settings: {}, created_at: new Date().toISOString() };
      state.projects.push(p);
      return [200, p];
    }
    case "create_project_api_key": {
      if (!state.projects.some((p) => p.id === args.p_project_id)) return [403, { code: "PT403", message: "not allowed", details: null, hint: null }];
      const prefix = `dw_${hex(5)}`;
      state.project_api_keys.push({
        id: randomUUID(), project_id: args.p_project_id, name: String(args.p_name), prefix,
        key_hash: "\\x" + hex(32), created_at: new Date().toISOString(), last_used_at: null, revoked_at: null,
      });
      return [200, `${prefix}_${hex(32)}`];
    }
    case "revoke_project_api_key": {
      const k = state.project_api_keys.find((x) => x.id === args.p_key_id);
      if (k && !k.revoked_at) k.revoked_at = new Date().toISOString();
      return [204, undefined];
    }
    case "export_my_data":
      return [200, {
        exported_at: new Date().toISOString(),
        profile: { id: USER.id, email: USER.email, created_at: USER.created_at },
        organizations: [{ id: ORG_ID, name: "Personal", created_by: USER.id }],
        memberships: [{ organization_id: ORG_ID, user_id: USER.id, role: "owner", status: "active" }],
        projects: state.projects,
        api_keys: state.project_api_keys.map(({ key_hash, ...meta }) => meta),
        signal_records_latest_10000: [...state.signal_records].sort((a, b) => (a.occurred_at < b.occurred_at ? 1 : -1)).slice(0, 10000),
        signal_hourly: state.signal_hourly,
        audit_events: [],
      }];
    // ---- cloud connect (0011). Only what the console calls; the sealed key is accepted and dropped, never stored.
    case "delete_connected_model":
      state.connected_models = state.connected_models.filter((m) => m.project_id !== args.p_project_id);
      return [204, undefined];
    case "update_connected_model": {
      const m = state.connected_models.find((x) => x.project_id === args.p_project_id);
      if (!m) return [204, undefined];
      if (args.p_interval_minutes < 15) return [422, { code: "PT422", message: "invalid settings", details: null, hint: null }];
      Object.assign(m, { interval_minutes: args.p_interval_minutes, monthly_budget: args.p_monthly_budget, enabled: args.p_enabled });
      return [204, undefined];
    }
    case "set_probes":
      state.connected_probes = state.connected_probes.filter((p) => p.project_id !== args.p_project_id);
      (args.p_probes ?? []).forEach((p, i) => state.connected_probes.push({ project_id: args.p_project_id, position: i + 1, ...p }));
      return [204, undefined];
    case "delete_my_account":
      state.deleted = true;
      return [204, undefined];
    // ---- device login (0009). Statuses mirror the SQL. A minted key is NOT added to project_api_keys,
    // so the console checks that count keys are unaffected.
    case "start_device_login": {
      const nm = String(args.p_device_name ?? "").trim();
      const os = String(args.p_device_os ?? "").trim();
      if (!nm || nm.length > 64 || !os || os.length > 64) return [422, { code: "PT422", message: "invalid device name", details: null, hint: null }];
      const alphabet = "BCDFGHJKLMNPQRSTVWXZ";
      let user_code = "";
      while (user_code.length < 8) user_code += alphabet[randomBytes(1)[0] % 20];
      const row = { device_code: hex(32), user_code, device_name: nm, device_os: os, created_at: new Date().toISOString(),
        last_polled_at: 0, approved_project_id: null, denied: false, consumed: false };
      state.device_codes.push(row);
      return [200, { device_code: row.device_code, user_code, expires_in: 600, interval: 5 }];
    }
    case "poll_device_login": {
      const row = state.device_codes.find((d) => d.device_code === args.p_device_code);
      if (!row || row.consumed) return [200, { status: "expired_token" }];
      if (row.denied) return [200, { status: "access_denied" }];
      if (!row.approved_project_id) {
        const fast = Date.now() - row.last_polled_at < 4000;
        row.last_polled_at = Date.now();
        return [200, { status: fast ? "slow_down" : "authorization_pending" }];
      }
      row.consumed = true;
      const project = state.projects.find((p) => p.id === row.approved_project_id);
      return [200, { status: "approved", api_key: `dw_${hex(5)}_${hex(32)}`, project_id: project.id, project_name: project.name }];
    }
    case "inspect_device_login":
    case "approve_device_login":
    case "deny_device_login": {
      if (state.device_wrong_codes >= 5) return [429, { code: "PT429", message: "too many wrong codes, wait 15 minutes", details: null, hint: null }];
      const code = String(args.p_user_code ?? "").toUpperCase().replace(/[\s-]/g, "");
      const row = state.device_codes.find((d) => d.user_code === code && !d.approved_project_id && !d.denied && !d.consumed);
      if (!row) {
        state.device_wrong_codes++;
        return [200, { status: "invalid" }];
      }
      if (name === "inspect_device_login") {
        return [200, { status: "pending", device_name: row.device_name, device_os: row.device_os, requested_at: row.created_at, expires_at: row.created_at }];
      }
      if (name === "deny_device_login") {
        row.denied = true;
        return [200, { status: "denied" }];
      }
      if (!state.projects.some((p) => p.id === args.p_project_id)) return [403, { code: "PT403", message: "forbidden", details: null, hint: null }];
      row.approved_project_id = args.p_project_id;
      return [200, { status: "approved" }];
    }
    default:
      return [404, { code: "PGRST202", message: `Could not find the function public.${name}`, details: null, hint: null }];
  }
}

const PUBLIC_COLUMNS = { project_api_keys: ["id", "project_id", "name", "prefix", "created_at", "last_used_at", "revoked_at"] };

async function handle(req, res) {
  const url = new URL(req.url, "http://fake");
  const path = url.pathname;
  if (req.method === "OPTIONS") {
    return send(req, res, 204, undefined, {
      "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
      "Access-Control-Allow-Headers": ALLOWED_HEADERS,
      "Access-Control-Max-Age": "600",
    });
  }
  let raw = "";
  for await (const chunk of req) raw += chunk;
  const body = raw ? JSON.parse(raw) : {};

  if (path === "/auth/v1/user" && req.method === "GET") {
    return authed(req) ? send(req, res, 200, USER) : send(req, res, 401, { code: 401, error_code: "bad_jwt", msg: "invalid" });
  }
  if (path === "/auth/v1/logout" && req.method === "POST") {
    state.logouts++;
    return send(req, res, 204);
  }
  if (path === "/auth/v1/token" && url.searchParams.get("grant_type") === "refresh_token") {
    if (state.deleted) return send(req, res, 400, { code: 400, error_code: "refresh_token_not_found", msg: "invalid" });
    return send(req, res, 200, {
      access_token: TOKEN, refresh_token: "fake-refresh", token_type: "bearer", expires_in: 3600,
      expires_at: Math.floor(Date.now() / 1000) + 10 * 365 * 86400, user: USER,
    });
  }

  const rest = path.match(/^\/rest\/v1\/(rpc\/)?([a-z_]+)$/);
  if (rest) {
    const [, isRpc, name] = rest;
    // The CLI has no session: these two are callable with the anon key only (as in 0009).
    const anonRpc = isRpc && ["start_device_login", "poll_device_login"].includes(name);
    if (!anonRpc && !authed(req)) return send(req, res, 401, { code: "PGRST301", message: "JWT invalid", details: null, hint: null });
    if (isRpc && req.method === "POST") {
      const [status, out] = rpc(name, body);
      return send(req, res, status, out);
    }
    if (!isRpc && req.method === "GET" && TABLES.includes(name)) {
      let rows = applyQuery(state[name], url.searchParams);
      const cols = PUBLIC_COLUMNS[name];
      if (cols) rows = rows.map((r) => Object.fromEntries(cols.map((c) => [c, r[c]])));
      if ((req.headers.accept ?? "").startsWith("application/vnd.pgrst.object+json")) {
        if (rows.length !== 1) {
          return send(req, res, 406, { code: "PGRST116", message: "JSON object requested, multiple (or no) rows returned", details: `The result contains ${rows.length} rows`, hint: null });
        }
        return send(req, res, 200, rows[0]);
      }
      return send(req, res, 200, rows);
    }
  }
  return send(req, res, 404, { code: "FAKE404", message: `fake-supabase: no route for ${req.method} ${path}` });
}

export function startFake({ host = "127.0.0.1", port = 54321, log = () => {} } = {}) {
  const server = createServer((req, res) => {
    log(`${req.method} ${req.url}`);
    handle(req, res).catch((e) => send(req, res, 500, { code: "FAKE500", message: String(e?.message ?? e) }));
  });
  // No Realtime: refuse websocket upgrades so the client sees a closed socket.
  server.on("upgrade", (req, socket) => {
    log(`UPGRADE ${req.url} (refused)`);
    socket.destroy();
  });
  return new Promise((resolve) => server.listen(port, host, () => resolve(server)));
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  await startFake({ log: console.log });
  console.log("fake-supabase listening on http://127.0.0.1:54321");
}
