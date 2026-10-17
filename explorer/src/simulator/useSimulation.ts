import { useEffect, useReducer, useRef, useState } from "react";
import type { Evidence } from "../types";
import { initialSession, sessionMessage } from "./types";
export function useSimulation() {
  const [session, dispatch] = useReducer(sessionMessage, initialSession),
    [data, setData] = useState<Evidence | null>(null),
    [status, setStatus] = useState("Connecting to local simulator…");
  const socket = useRef<WebSocket | null>(null),
    worker = useRef<Worker | null>(null),
    sequence = useRef(0),
    pendingText = useRef(new Map<number, (s: string) => void>());
  useEffect(() => {
    let cancelled = false;
    let ws: WebSocket | null = null;
    const w = new Worker(new URL("../bundle.worker.ts", import.meta.url), {
      type: "module",
    });
    worker.current = w;
    w.onmessage = ({ data: m }) => {
      if (cancelled) return;
      if (m.type === "loaded") setData(m.evidence);
      else if (m.type === "text") {
        pendingText.current.get(m.id)?.(m.text);
        pendingText.current.delete(m.id);
      } else if (m.type === "error") setStatus(m.error);
    };
    void (async () => {
      try {
        const response = await fetch("/api/simulator/status");
        if (!response.ok)
          throw new Error(
            "Start the local backend with gmake simulator-dev or gmake simulator-serve.",
          );
        const config = await response.json();
        if (!config.available) throw new Error(config.error);
        if (cancelled) return;
        const bundle = await fetch("/api/simulator/evidence");
        if (!bundle.ok) throw new Error(await bundle.text());
        const bytes = await bundle.arrayBuffer();
        if (cancelled) return;
        w.postMessage({ type: "load", id: ++sequence.current, bytes }, [bytes]);
        ws = new WebSocket(
          `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/simulator/ws?token=${encodeURIComponent(config.token)}`,
        );
        socket.current = ws;
        ws.onopen = () => {
          if (!cancelled) {
            dispatch({ type: "connected" });
            setStatus("");
          }
        };
        ws.onmessage = (event) => {
          if (!cancelled) dispatch(JSON.parse(event.data));
        };
        ws.onclose = () => {
          if (!cancelled)
            setStatus(
              "Simulator disconnected. Reload this window to start a new session.",
            );
        };
        ws.onerror = () => {
          if (!cancelled)
            setStatus(
              "Cannot connect to the local simulator. Another window may own the active session.",
            );
        };
      } catch (e) {
        if (!cancelled) setStatus(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
      ws?.close();
      w.terminate();
      pendingText.current.clear();
    };
  }, []);
  const command = (command: string, args: Record<string, unknown> = {}) => {
    if (socket.current?.readyState !== WebSocket.OPEN) return;
    socket.current.send(
      JSON.stringify({
        requestId: ++sequence.current,
        generation: session.generation,
        command,
        ...args,
      }),
    );
    if (["start", "restart", "step", "continue", "stage"].includes(command))
      dispatch({
        type: "running",
        generation: session.generation,
        target: command === "stage" ? args.node : session.target,
      });
  };
  const getText = (path: string) =>
    new Promise<string>((resolve) => {
      const id = ++sequence.current;
      pendingText.current.set(id, resolve);
      worker.current?.postMessage({ type: "text", id, path });
    });
  return { session, data, status, command, getText };
}
