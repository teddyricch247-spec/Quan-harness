"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { GithubCredential, McpServer } from "@/lib/types";
import { looksLikeRepo } from "@/lib/format";
import { CheckIcon } from "./icons";
import Sheet from "./Sheet";

export type ProjectSource =
  | { kind: "scratch" }
  | { kind: "import"; repo: string }
  | { kind: "create"; name: string; isPrivate: boolean };

/**
 * Code home's "+": project *setup* (C4: "Home's + is project setup (start from, connectors,
 * images). The workspace + is this project"). Start from scratch (the default), import a
 * repository, or create a new one; plus the connector switches, which become `connector_ids` on the
 * create call (none by default).
 *
 * Import and Create need a GitHub credential. With none, the row reads "Connect GitHub first →" and
 * leaves for the GitHub page (the caller stashes a return path; the draft is already persisted).
 * The API also answers `github_not_connected` if this guess is wrong, so the UI never depends on
 * string-matching.
 *
 * Not here, on purpose: image attachments (they need a session, and POST /projects creates the session and starts
 * the first turn in one call; attach pictures from the workspace's + once the project exists) and a
 * repository *picker* (no endpoint lists a GitHub account's repositories) — importing takes a typed
 * `owner/repo`.
 */
export default function NewProjectSheet({
  open,
  onClose,
  source,
  onSource,
  githubCredentials,
  connectors,
  connectorIds,
  onConnectorIds,
  onLeaveToConnectGithub,
}: {
  open: boolean;
  onClose: () => void;
  source: ProjectSource;
  onSource: (source: ProjectSource) => void;
  githubCredentials: GithubCredential[];
  connectors: McpServer[];
  connectorIds: string[];
  onConnectorIds: (ids: string[]) => void;
  onLeaveToConnectGithub: () => void;
}) {
  const hasGithub = githubCredentials.length > 0;
  const [repoText, setRepoText] = useState(source.kind === "import" ? source.repo : "");
  const [newName, setNewName] = useState(source.kind === "create" ? source.name : "");
  const [isPrivate, setIsPrivate] = useState(source.kind === "create" ? source.isPrivate : true);
  const [mode, setMode] = useState<ProjectSource["kind"]>(source.kind);

  useEffect(() => {
    if (open) setMode(source.kind);
  }, [open, source.kind]);

  const usable = connectors.filter((c) => c.enabled);

  function commit(nextMode: ProjectSource["kind"], repo = repoText, name = newName, priv = isPrivate) {
    if (nextMode === "scratch") onSource({ kind: "scratch" });
    else if (nextMode === "import") onSource(looksLikeRepo(repo) ? { kind: "import", repo: repo.trim() } : { kind: "scratch" });
    else onSource(name.trim() ? { kind: "create", name: name.trim(), isPrivate: priv } : { kind: "scratch" });
  }

  const option = (key: ProjectSource["kind"], title: string, detail: string, needsGithub: boolean) => {
    const selected = mode === key;
    if (needsGithub && !hasGithub) {
      return (
        <Link href="/connections/github" onClick={onLeaveToConnectGithub} className="row">
          <span className="flex-1">
            <span className="block">{title}</span>
            <span className="block text-xs text-muted">Connect GitHub first →</span>
          </span>
        </Link>
      );
    }
    return (
      <button
        className="row"
        aria-pressed={selected}
        onClick={() => {
          setMode(key);
          commit(key);
        }}
      >
        <span className="flex-1">
          <span className="block">{title}</span>
          <span className="block text-xs text-muted">{detail}</span>
        </span>
        {selected && <CheckIcon />}
      </button>
    );
  };

  return (
    <Sheet open={open} onClose={onClose} title="New project">
      <p className="px-4 pt-3 pb-1 text-xs text-muted">Start from</p>
      {option("scratch", "From scratch", "No repository. Nothing is created on GitHub.", false)}
      {option("import", "Import a repository", "Pulls its default branch into the workspace.", true)}
      {mode === "import" && hasGithub && (
        <div className="px-4 py-3 border-b border-line">
          <label className="label" htmlFor="import-repo">
            Repository
          </label>
          <input
            id="import-repo"
            className="input mono"
            placeholder="owner/repo"
            value={repoText}
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            onChange={(e) => {
              setRepoText(e.target.value);
              commit("import", e.target.value);
            }}
          />
          {repoText && !looksLikeRepo(repoText) && <p className="text-xs text-muted mt-1">Use the form owner/repo.</p>}
        </div>
      )}
      {option("create", "Create a new repository", "Private by default.", true)}
      {mode === "create" && hasGithub && (
        <div className="px-4 py-3 border-b border-line space-y-2">
          <div>
            <label className="label" htmlFor="new-repo-name">
              Repository name
            </label>
            <input
              id="new-repo-name"
              className="input mono"
              placeholder="my-new-app"
              value={newName}
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              onChange={(e) => {
                setNewName(e.target.value);
                commit("create", repoText, e.target.value);
              }}
            />
          </div>
          <label className="flex items-center gap-2 text-sm min-h-[36px]">
            <input
              type="checkbox"
              checked={isPrivate}
              onChange={(e) => {
                setIsPrivate(e.target.checked);
                commit("create", repoText, newName, e.target.checked);
              }}
            />
            Private repository
          </label>
        </div>
      )}

      <p className="px-4 pt-4 pb-1 text-xs text-muted">Connectors for this project</p>
      {usable.length === 0 ? (
        <Link href="/connections/connectors" className="row text-sm">
          No connectors yet — add one in Settings
        </Link>
      ) : (
        <ul>
          {usable.map((c) => {
            const on = connectorIds.includes(c.id);
            return (
              <li key={c.id}>
                <label className="row cursor-pointer">
                  <span className="flex-1 min-w-0">
                    <span className="block truncate">{c.name}</span>
                    <span className="block truncate text-xs text-muted mono">{c.url}</span>
                  </span>
                  <input
                    type="checkbox"
                    role="switch"
                    checked={on}
                    aria-label={`Give this project access to ${c.name}`}
                    onChange={() => onConnectorIds(on ? connectorIds.filter((id) => id !== c.id) : [...connectorIds, c.id])}
                  />
                </label>
              </li>
            );
          })}
        </ul>
      )}
      <div className="p-4">
        <button className="btn-primary w-full" onClick={onClose}>
          Done
        </button>
      </div>
    </Sheet>
  );
}
