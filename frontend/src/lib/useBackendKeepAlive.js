import { useEffect } from 'react';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL;
const PING_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

// Render's free tier spins the backend down after ~15 min idle, and cold starts
// take a while — bad news mid-session. This pings /health (no auth required) once
// on load and then every 5 minutes for as long as the tab stays open, keeping the
// backend warm. Fire-and-forget: errors are swallowed so a slow/asleep backend
// never blocks or breaks the UI.
function pingBackend() {
  if (!BACKEND_URL) return;
  fetch(`${BACKEND_URL}/health`).catch(() => {});
}

export function useBackendKeepAlive() {
  useEffect(() => {
    pingBackend();
    const id = setInterval(pingBackend, PING_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);
}
