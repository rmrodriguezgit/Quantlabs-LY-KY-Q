import { useCallback, useEffect, useState } from "react";
import type { Config, Snapshot } from "./types";

const WS_URL = import.meta.env.VITE_LAYA_WS ?? "ws://127.0.0.1:8000/ws";
const API = import.meta.env.VITE_LAYA_API ?? "http://127.0.0.1:8000";

export function useLaya() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer = 0;
    let stopped = false;
    let delay = 500;

    const open = () => {
      ws = new WebSocket(WS_URL);
      ws.onopen = () => {
        setConnected(true);
        delay = 500;
      };
      ws.onmessage = (e) => setSnap(JSON.parse(e.data) as Snapshot);
      ws.onclose = () => {
        setConnected(false);
        if (!stopped) {
          delay = Math.min(delay * 2, 5000);
          timer = window.setTimeout(open, delay);
        }
      };
    };
    open();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  const setConfig = useCallback(async (c: Partial<Config>) => {
    await fetch(`${API}/api/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(c),
    });
  }, []);

  return { snap, connected, setConfig };
}
