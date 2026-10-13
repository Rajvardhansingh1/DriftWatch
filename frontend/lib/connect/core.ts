// Cloud connect, server side and pure: every function takes its dependencies, so tests can prove what is sent where.
// The provider key travels only: browser -> this server action -> (a) one validation call to the provider's fixed host
// and (b) sealed with the runner's PUBLIC key into the database. Plaintext is never stored, logged or returned.
import { friendlyError, type ActionResult, type RpcClient } from "@/lib/console/actions-core";
import { isUuid } from "@/lib/console/validate";
import type { SealedBox } from "./seal";

export const PROVIDERS = ["groq", "openai"] as const;
export type Provider = (typeof PROVIDERS)[number];

const HOSTS: Record<Provider, string> = {
  groq: "https://api.groq.com/openai/v1/chat/completions",
  openai: "https://api.openai.com/v1/chat/completions",
};
const MODEL_RE = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}$/;
const KEY_RE = /^[\x21-\x7e]{8,512}$/; // visible ASCII, no spaces
const GENERIC = "Something went wrong. Please try again.";

export type ProbeInput = { prompt: string; expected: string; match_type: "contains" | "exact" };

// Neutral starter probes: no personal data, short, and answerable by any current chat model.
export const STARTER_PROBES: ProbeInput[] = [
  { prompt: "What is 12 + 7? Answer with just the number.", expected: "19", match_type: "contains" },
  { prompt: "What is the capital of France? Answer with just the city name.", expected: "Paris", match_type: "contains" },
  { prompt: "Reply with exactly one word: OK", expected: "OK", match_type: "contains" },
  { prompt: "Is the sentence 'The sky is green' true or false? Answer with one word.", expected: "false", match_type: "contains" },
  { prompt: "If a train leaves at 3 pm and the trip takes 2 hours, what time does it arrive? Answer like 5 pm.", expected: "5 pm", match_type: "contains" },
];

export type ConnectInput = { provider: Provider; model: string; apiKey: string; intervalMinutes: number; monthlyBudget: number };
type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

const isInt = (v: unknown, lo: number, hi: number): v is number => typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi;

export function parseConnectInput(raw: unknown): Parsed<ConnectInput> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { ok: false, error: "That request was not accepted." };
  const r = raw as Record<string, unknown>;
  if (!PROVIDERS.includes(r.provider as Provider)) return { ok: false, error: "Choose Groq or OpenAI." };
  if (typeof r.model !== "string" || !MODEL_RE.test(r.model)) return { ok: false, error: "Enter the model name, for example llama-3.3-70b-versatile." };
  if (typeof r.apiKey !== "string" || !KEY_RE.test(r.apiKey)) return { ok: false, error: "That does not look like an API key." };
  const intervalMinutes = r.intervalMinutes ?? 60;
  const monthlyBudget = r.monthlyBudget ?? 2000;
  if (!isInt(intervalMinutes, 15, 1440)) return { ok: false, error: "Run every 15 to 1440 minutes." };
  if (!isInt(monthlyBudget, 1, 100000)) return { ok: false, error: "Set a monthly call budget between 1 and 100000." };
  return { ok: true, value: { provider: r.provider as Provider, model: r.model, apiKey: r.apiKey, intervalMinutes, monthlyBudget } };
}

export type Verdict = "ok" | "rejected" | "unknown_model" | "unreachable";

/** One one-token call to the provider's fixed host. A verdict only: no provider text is ever passed on. */
export async function validateProviderKey(fetchFn: typeof fetch, provider: string, model: string, key: string): Promise<Verdict> {
  const url = HOSTS[provider as Provider];
  if (!url) return "unreachable";
  try {
    const r = await fetchFn(url, {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "content-type": "application/json" },
      body: JSON.stringify({ model, messages: [{ role: "user", content: "Reply with OK" }], max_tokens: 1, temperature: 0 }),
      redirect: "error",
      signal: AbortSignal.timeout(15000),
    });
    if (r.status === 200 || r.status === 429) return "ok"; // a rate-limited key is still a valid key
    if (r.status === 401 || r.status === 403) return "rejected";
    if (r.status === 404 || r.status === 400) return "unknown_model";
    return "unreachable";
  } catch {
    return "unreachable";
  }
}

export interface ConnectDeps {
  enabled: boolean;
  publicKey: string;
  keyId: number;
  newId: () => string;
  check: (provider: string, model: string, key: string) => Promise<Verdict>;
  seal: (plaintext: string, modelId: string, keyId: number, publicKey: string) => SealedBox;
}

const VERDICT_TEXT: Record<Exclude<Verdict, "ok">, string> = {
  rejected: "The provider rejected that key. Check it and try again.",
  unknown_model: "The provider does not know that model name for this key.",
  unreachable: "We could not reach the provider to check the key. Try again in a moment.",
};

// Fixed sentences only: the database's own message is never passed on here, because the request carried a sealed key.
function connectError(code: string | undefined, _message: string | undefined): string {
  if (code === "PT503") return "Cloud connect is not available right now.";
  if (code === "PT422") return "Those settings were not accepted. Check the model name, schedule and budget.";
  return friendlyError({ code });
}

export async function connectModelCore(client: RpcClient, deps: ConnectDeps, projectId: unknown, raw: unknown): Promise<ActionResult<{ last4: string }>> {
  if (!deps.enabled || !deps.publicKey) return { ok: false, error: "Cloud connect is not available right now." };
  if (!isUuid(projectId)) return { ok: false, error: "Unknown project." };
  const parsed = parseConnectInput(raw);
  if (!parsed.ok) return parsed;
  const { provider, model, apiKey, intervalMinutes, monthlyBudget } = parsed.value;
  try {
    const verdict = await deps.check(provider, model, apiKey);
    if (verdict !== "ok") return { ok: false, error: VERDICT_TEXT[verdict] };
    const modelId = deps.newId();
    const box = deps.seal(apiKey, modelId, deps.keyId, deps.publicKey);
    const last4 = apiKey.slice(-4);
    const { error } = await client.rpc("connect_model", {
      p_project_id: projectId,
      p_model_id: modelId,
      p_provider: provider,
      p_model: model,
      p_last4: last4,
      p_key_id: box.key_id,
      p_ephemeral: box.ephemeral,
      p_nonce: box.nonce,
      p_ciphertext: box.ciphertext,
      p_interval_minutes: intervalMinutes,
      p_monthly_budget: monthlyBudget,
    });
    if (error) return { ok: false, error: connectError(error.code, error.message) };
    return { ok: true, last4 };
  } catch {
    return { ok: false, error: GENERIC }; // the message of a thrown error could carry the key
  }
}

export function parseProbes(raw: unknown): Parsed<ProbeInput[]> {
  if (!Array.isArray(raw) || raw.length < 1 || raw.length > 5) return { ok: false, error: "Add between 1 and 5 probes." };
  const out: ProbeInput[] = [];
  for (const p of raw) {
    if (!p || typeof p !== "object") return { ok: false, error: "A probe was not valid." };
    const { prompt, expected, match_type } = p as Record<string, unknown>;
    if (typeof prompt !== "string" || typeof expected !== "string") return { ok: false, error: "A probe needs a question and an expected answer." };
    const q = prompt.trim();
    const a = expected.trim();
    if (q.length < 1 || q.length > 500) return { ok: false, error: "A question must be 1 to 500 characters." };
    if (a.length < 1 || a.length > 200) return { ok: false, error: "An expected answer must be 1 to 200 characters." };
    if (match_type !== "contains" && match_type !== "exact") return { ok: false, error: "Match type must be contains or exact." };
    out.push({ prompt: q, expected: a, match_type });
  }
  return { ok: true, value: out };
}

export async function setProbesCore(client: RpcClient, projectId: unknown, raw: unknown): Promise<ActionResult> {
  if (!isUuid(projectId)) return { ok: false, error: "Unknown project." };
  const probes = parseProbes(raw);
  if (!probes.ok) return probes;
  const { error } = await client.rpc("set_probes", { p_project_id: projectId, p_probes: probes.value });
  return error ? { ok: false, error: connectError(error.code, error.message) } : { ok: true };
}

export async function updateConnectionCore(
  client: RpcClient,
  projectId: unknown,
  raw: { intervalMinutes: unknown; monthlyBudget: unknown; enabled: unknown },
): Promise<ActionResult> {
  if (!isUuid(projectId)) return { ok: false, error: "Unknown project." };
  if (!isInt(raw.intervalMinutes, 15, 1440)) return { ok: false, error: "Run every 15 to 1440 minutes." };
  if (!isInt(raw.monthlyBudget, 1, 100000)) return { ok: false, error: "Set a monthly call budget between 1 and 100000." };
  if (typeof raw.enabled !== "boolean") return { ok: false, error: "That request was not accepted." };
  const { error } = await client.rpc("update_connected_model", {
    p_project_id: projectId,
    p_interval_minutes: raw.intervalMinutes,
    p_monthly_budget: raw.monthlyBudget,
    p_enabled: raw.enabled,
  });
  return error ? { ok: false, error: connectError(error.code, error.message) } : { ok: true };
}

export async function deleteConnectionCore(client: RpcClient, projectId: unknown): Promise<ActionResult> {
  if (!isUuid(projectId)) return { ok: false, error: "Unknown project." };
  const { error } = await client.rpc("delete_connected_model", { p_project_id: projectId });
  return error ? { ok: false, error: connectError(error.code, error.message) } : { ok: true };
}

const TOKENS_PER_CALL_CEILING = 450; // at most 256 answer tokens plus a 500-character question and the short system prompt

/** What the schedule can cost the user, as calls and a token ceiling. Never a price: prices are the provider's. */
export function estimateUsage(s: { probes: number; intervalMinutes: number; monthlyBudget: number }) {
  const callsPerRun = s.probes + 2; // the probes, plus two re-asks of the first for the self-consistency signal
  const runsPerMonth = Math.floor((30 * 24 * 60) / s.intervalMinutes);
  const callsPerMonth = Math.min(s.monthlyBudget, callsPerRun * runsPerMonth);
  return { callsPerRun, runsPerMonth, callsPerMonth, tokensCeiling: callsPerMonth * TOKENS_PER_CALL_CEILING };
}

export type RunStatus = "waiting" | "ok" | "late" | "error" | "paused";

export function runStatus(
  m: { enabled: boolean; interval_minutes: number; last_run_at: string | null; last_error: string | null },
  now: number,
): RunStatus {
  if (!m.enabled) return "paused";
  if (m.last_error) return "error";
  if (!m.last_run_at) return "waiting";
  return now - Date.parse(m.last_run_at) > 2 * m.interval_minutes * 60_000 ? "late" : "ok";
}
