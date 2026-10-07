import { isUuid } from "./validate";
import type { Row } from "./series";

export type LiveStatus = "connecting" | "live" | "offline";

export interface ChannelLike {
  on(type: string, filter: Record<string, unknown>, cb: (payload: { new: unknown }) => void): ChannelLike;
  subscribe(cb?: (status: string) => void): ChannelLike;
}
export interface ClientLike {
  channel(name: string): ChannelLike;
  removeChannel(channel: ChannelLike): unknown;
}

function isRow(v: unknown): v is Row {
  if (!v || typeof v !== "object") return false;
  const r = v as Record<string, unknown>;
  return typeof r.signal === "string" && typeof r.value === "number" && typeof r.occurred_at === "string";
}

function toStatus(raw: string): LiveStatus {
  if (raw === "SUBSCRIBED") return "live";
  if (raw === "CHANNEL_ERROR" || raw === "TIMED_OUT" || raw === "CLOSED") return "offline";
  return "connecting";
}

// INSERT only, one project: Postgres-changes DELETE events bypass row-level
// security, and the nightly prune would flood every subscriber.
export function subscribeToProject(
  client: ClientLike,
  projectId: string,
  onRow: (row: Row) => void,
  onStatus: (status: LiveStatus) => void,
): () => void {
  if (!isUuid(projectId)) throw new Error("invalid project id");
  const channel = client
    .channel(`project-${projectId}`)
    .on(
      "postgres_changes",
      { event: "INSERT", schema: "public", table: "signal_records", filter: `project_id=eq.${projectId}` },
      (payload) => {
        if (isRow(payload.new)) onRow(payload.new);
      },
    )
    .subscribe((status) => onStatus(toStatus(status)));
  return () => {
    client.removeChannel(channel);
  };
}
