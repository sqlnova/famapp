import { useEffect, useRef, useState, useCallback } from "react";

/**
 * WebSocket hook that:
 *  - Accepts a server URL
 *  - Bootstraps from the 'snapshot' message on connect
 *  - Appends incoming 'event' messages to a capped feed (last 20 shown)
 *  - Auto-reconnects with exponential backoff on disconnect
 *
 * Returns: { agents: {[name]: agentState}, events: event[], connection }
 *   connection: 'connecting' | 'open' | 'closed'
 */
export default function useMonitoringSocket(url, { maxEvents = 20 } = {}) {
  const [agents, setAgents] = useState({});
  const [events, setEvents] = useState([]);
  const [connection, setConnection] = useState("connecting");

  const wsRef = useRef(null);
  const reconnectAttempt = useRef(0);
  const closedByUs = useRef(false);
  const reconnectTimer = useRef(null);

  const applyEvent = useCallback((ev) => {
    setAgents((prev) => ({ ...prev, [ev.agent_name]: ev }));
    setEvents((prev) => {
      const next = [ev, ...prev];
      return next.slice(0, maxEvents);
    });
  }, [maxEvents]);

  const applySnapshot = useCallback((snap) => {
    if (Array.isArray(snap.agents)) {
      const map = {};
      for (const a of snap.agents) map[a.agent_name] = a;
      setAgents(map);
    }
    if (Array.isArray(snap.events)) {
      const recent = [...snap.events].reverse().slice(0, maxEvents);
      setEvents(recent);
    }
  }, [maxEvents]);

  useEffect(() => {
    closedByUs.current = false;

    const connect = () => {
      setConnection("connecting");
      let ws;
      try {
        ws = new WebSocket(url);
      } catch (err) {
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttempt.current = 0;
        setConnection("open");
      };

      ws.onmessage = (evt) => {
        let data;
        try {
          data = JSON.parse(evt.data);
        } catch {
          return;
        }
        if (data.type === "snapshot") {
          applySnapshot(data);
        } else if (data.type === "event" && data.event) {
          applyEvent(data.event);
        }
      };

      ws.onerror = () => {
        // Let onclose drive reconnection.
      };

      ws.onclose = () => {
        setConnection("closed");
        if (!closedByUs.current) scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      const attempt = Math.min(reconnectAttempt.current + 1, 6);
      reconnectAttempt.current = attempt;
      const delay = Math.min(1000 * 2 ** (attempt - 1), 15000);
      reconnectTimer.current = setTimeout(connect, delay);
    };

    connect();

    return () => {
      closedByUs.current = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {}
      }
    };
  }, [url, applyEvent, applySnapshot]);

  return { agents, events, connection };
}
