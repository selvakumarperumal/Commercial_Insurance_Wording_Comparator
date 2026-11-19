import { useEffect, useEffectEvent } from "react";
import { api } from "./api.js";

// Live job status from GET /jobs/stream (Server-Sent Events).
// onReady runs once subscribed (and after every reconnect), so the caller reloads the job list then;
// onStatus runs with {job_id, status} on every status change.
export function useJobEvents(onReady, onStatus) {
  const ready = useEffectEvent(onReady);
  const status = useEffectEvent(onStatus);

  useEffect(() => {
    const source = new EventSource(api.streamUrl());
    source.addEventListener("ready", () => ready());
    source.onmessage = (event) => status(JSON.parse(event.data));
    return () => source.close();
  }, []);
}
