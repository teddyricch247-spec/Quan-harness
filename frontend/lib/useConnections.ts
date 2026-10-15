"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "./api";
import type { GithubCredential, LlmCredential, McpServer } from "./types";

/**
 * The three account-level lists Code home and the workspace need to decide what to offer: model
 * keys (is there one? which is the default?), GitHub connections (can Import / Create run?) and
 * connectors (the switches in the + sheet). A list that fails to load reads as empty and `loaded`
 * still flips — the screens treat "couldn't tell" as "nothing connected" and the server remains the
 * authority (it answers `llm_key_required` / `github_not_connected` either way).
 */
export function useConnections(): {
  llm: LlmCredential[];
  github: GithubCredential[];
  connectors: McpServer[];
  loaded: boolean;
  reload: () => void;
} {
  const [llm, setLlm] = useState<LlmCredential[]>([]);
  const [github, setGithub] = useState<GithubCredential[]>([]);
  const [connectors, setConnectors] = useState<McpServer[]>([]);
  const [loaded, setLoaded] = useState(false);

  const reload = useCallback(() => {
    Promise.all([
      apiFetch<LlmCredential[]>("/connections/llm-credentials").then(setLlm).catch(() => setLlm([])),
      apiFetch<GithubCredential[]>("/connections/github-credential").then(setGithub).catch(() => setGithub([])),
      apiFetch<McpServer[]>("/connections/connectors").then(setConnectors).catch(() => setConnectors([])),
    ]).finally(() => setLoaded(true));
  }, []);

  useEffect(reload, [reload]);

  return { llm, github, connectors, loaded, reload };
}

export function defaultLlm(list: LlmCredential[]): LlmCredential | null {
  return list.find((c) => c.is_default) ?? list[0] ?? null;
}
