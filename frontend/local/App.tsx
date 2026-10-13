import React, { useCallback, useEffect, useState } from "react";
import type { SignalSeries } from "@/lib/types";
import { ApiError, getJson, openSession, toSeries, tokenFromHash, type LocalRange } from "./api";
import { View } from "./View";

const POLL_MS = 5000;
const empty = toSeries(null);

type Status = { sync?: { state?: string; pending?: number }; embedder?: string } | null;

export function App() {
  const [signedIn, setSignedIn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [projects, setProjects] = useState<string[]>([]);
  const [project, setProject] = useState<string | null>(null);
  const [range, setRange] = useState<LocalRange>("24h");
  const [series, setSeries] = useState<SignalSeries>(empty);
  const [status, setStatus] = useState<Status>(null);

  // Trade the one-time token in the fragment for the session cookie, then remove it from the address bar.
  // Runs on load and whenever a new link is opened in this same tab (only the fragment changes).
  useEffect(() => {
    const signIn = async () => {
      const token = tokenFromHash(window.location.hash);
      if (token) {
        const ok = await openSession(fetch, token);
        window.history.replaceState(null, "", window.location.pathname);
        if (!ok) return setError("That link did not work. Run `driftwatch dashboard` again for a new one.");
        setError(null);
      }
      try {
        await getJson(fetch, "/api/status");
        setSignedIn(true);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 401)) {
          setError("The agent did not answer. Is it still running? Try `driftwatch agent status`.");
        }
      }
    };
    signIn();
    window.addEventListener("hashchange", signIn);
    return () => window.removeEventListener("hashchange", signIn);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [list, st] = await Promise.all([getJson<string[]>(fetch, "/api/projects"), getJson<Status>(fetch, "/api/status")]);
      setProjects(list);
      setStatus(st);
      const current = project && list.includes(project) ? project : (list[0] ?? null);
      setProject(current);
      if (current) {
        setSeries(toSeries(await getJson(fetch, `/api/series?project=${encodeURIComponent(current)}&range=${range}`)));
      }
    } catch {
      setStatus(null); // the chip then reads "Offline", never a stale "Synced"
    }
  }, [project, range]);

  useEffect(() => {
    if (!signedIn) return;
    refresh();
    const id = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(id);
  }, [signedIn, refresh]);

  return (
    <View
      projects={projects}
      project={project}
      range={range}
      series={series}
      status={status}
      embedder={status?.embedder}
      signedIn={signedIn}
      error={error}
      onProject={setProject}
      onRange={setRange}
    />
  );
}
