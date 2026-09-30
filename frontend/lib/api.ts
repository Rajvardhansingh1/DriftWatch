import type {
  QueryResponse,
  QuotaState,
  ScenarioActivationResult,
  ScenarioName,
  ScenarioState,
  ScoreState,
  SignalSeries,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_MONITOR_API_URL ?? "http://localhost:8000";

/** Network failure or the server itself erroring (5xx) - the server is unreachable/broken. */
export class MonitorUnreachableError extends Error {}

/** The server responded but rejected the request (4xx) - a client input problem, not an outage. */
export class MonitorRequestError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (err) {
    throw new MonitorUnreachableError(err instanceof Error ? err.message : String(err));
  }
  if (!resp.ok) {
    if (resp.status >= 400 && resp.status < 500) {
      let detail = `request rejected (${resp.status})`;
      try {
        const body = await resp.json();
        detail = body?.detail ?? detail;
      } catch {
        // non-JSON error body - keep the generic message
      }
      throw new MonitorRequestError(resp.status, typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    throw new MonitorUnreachableError(`monitor returned ${resp.status}`);
  }
  return (await resp.json()) as T;
}

export function getHealth(): Promise<{ status: string }> {
  return request("/api/health");
}

export function getQuota(): Promise<QuotaState> {
  return request("/api/quota");
}

export function getSignals(limit = 50): Promise<SignalSeries> {
  return request(`/api/signals?limit=${limit}`);
}

export function getScore(): Promise<ScoreState> {
  return request("/api/score");
}

export function getScenarioState(): Promise<ScenarioState> {
  return request("/api/scenario/state");
}

export function postQuery(text?: string): Promise<QueryResponse> {
  return request("/api/query", {
    method: "POST",
    body: JSON.stringify({ text: text ?? null }),
  });
}

export function postScenario(
  name: ScenarioName,
  action: "activate" | "reset"
): Promise<ScenarioActivationResult> {
  return request(`/api/scenario/${name}`, {
    method: "POST",
    body: JSON.stringify({ action }),
  });
}

export function resetAllScenarios(): Promise<{ status: string }> {
  return request("/api/scenario/reset", { method: "POST" });
}
