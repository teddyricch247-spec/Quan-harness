"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import NavBar from "@/components/NavBar";
import AuthGuard from "@/components/AuthGuard";
import ErrorBanner from "@/components/ErrorBanner";
import { apiFetch, ApiError } from "@/lib/api";
import { GithubCredential, LlmCredential, McpServer, Project } from "@/lib/types";

type Mode = "scratch" | "import" | "create_new_repo";

function NewProjectWizard() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [githubCreds, setGithubCreds] = useState<GithubCredential[]>([]);
  const [llmCreds, setLlmCreds] = useState<LlmCredential[]>([]);
  const [connectors, setConnectors] = useState<McpServer[]>([]);

  // Step 1
  const [name, setName] = useState("");
  // Step 2
  const [mode, setMode] = useState<Mode>("scratch");
  const [githubRepo, setGithubRepo] = useState("");
  const [newRepoName, setNewRepoName] = useState("");
  const [newRepoPrivate, setNewRepoPrivate] = useState(true);
  const [githubCredentialId, setGithubCredentialId] = useState("");
  const [llmCredentialId, setLlmCredentialId] = useState("");
  // Step 3
  const [connectorIds, setConnectorIds] = useState<string[]>([]);

  useEffect(() => {
    apiFetch<GithubCredential[]>("/connections/github-credential").then(setGithubCreds).catch(() => {});
    apiFetch<LlmCredential[]>("/connections/llm-credentials").then(setLlmCreds).catch(() => {});
    apiFetch<McpServer[]>("/connections/connectors")
      .then((rows) => setConnectors(rows.filter((r) => r.enabled)))
      .catch(() => {});
  }, []);

  function canAdvanceFrom(s: number): boolean {
    if (s === 1) return name.trim().length > 0;
    if (s === 2) {
      if (mode === "import") return githubRepo.trim().length > 0 && Boolean(githubCredentialId);
      if (mode === "create_new_repo") return newRepoName.trim().length > 0 && Boolean(githubCredentialId);
      return true;
    }
    return true;
  }

  async function execute() {
    setBusy(true);
    setError(null);
    try {
      const project = await apiFetch<Project>("/projects", {
        method: "POST",
        body: JSON.stringify({
          name,
          mode,
          github_repo: mode === "import" ? githubRepo : undefined,
          new_repo_name: mode === "create_new_repo" ? newRepoName : undefined,
          new_repo_private: newRepoPrivate,
          github_credential_id: githubCredentialId || undefined,
          llm_credential_id: llmCredentialId || undefined,
          connector_ids: connectorIds,
        }),
      });
      router.replace(`/projects/${project.id}`);
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(false);
    }
  }

  return (
    <div className="max-w-lg mx-auto">
      <h1 className="text-lg font-semibold mb-1">New Project</h1>
      <p className="text-sm text-muted mb-6">Step {step} of 4</p>
      <ErrorBanner message={error} />

      {step === 1 && (
        <div className="card space-y-3">
          <div>
            <label className="label">Project name</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="card space-y-4">
          <div>
            <label className="label">Repository</label>
            <div className="space-y-2">
              <label className="flex items-start gap-2 text-sm border border-line rounded-md p-3 cursor-pointer">
                <input
                  type="radio"
                  checked={mode === "scratch"}
                  onChange={() => setMode("scratch")}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-medium">Start from scratch</span>
                  <br />
                  <span className="text-muted">
                    No repository, no GitHub credential required. Nothing is created on GitHub.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm border border-line rounded-md p-3 cursor-pointer">
                <input
                  type="radio"
                  checked={mode === "import"}
                  onChange={() => setMode("import")}
                  className="mt-0.5"
                />
                <span className="font-medium">Import an existing repository</span>
              </label>
              {mode === "import" && (
                <div className="pl-6 space-y-2">
                  <input
                    className="input"
                    placeholder="owner/repo"
                    value={githubRepo}
                    onChange={(e) => setGithubRepo(e.target.value)}
                  />
                  <CredentialSelect
                    creds={githubCreds}
                    value={githubCredentialId}
                    onChange={setGithubCredentialId}
                  />
                </div>
              )}
              <label className="flex items-start gap-2 text-sm border border-line rounded-md p-3 cursor-pointer">
                <input
                  type="radio"
                  checked={mode === "create_new_repo"}
                  onChange={() => setMode("create_new_repo")}
                  className="mt-0.5"
                />
                <span className="font-medium">Create a new repository right now</span>
              </label>
              {mode === "create_new_repo" && (
                <div className="pl-6 space-y-2">
                  <input
                    className="input"
                    placeholder="repository name"
                    value={newRepoName}
                    onChange={(e) => setNewRepoName(e.target.value)}
                  />
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={newRepoPrivate}
                      onChange={(e) => setNewRepoPrivate(e.target.checked)}
                    />
                    Private
                  </label>
                  <CredentialSelect
                    creds={githubCreds}
                    value={githubCredentialId}
                    onChange={setGithubCredentialId}
                  />
                </div>
              )}
              {githubCreds.length === 0 && mode !== "scratch" && (
                <p className="text-xs text-muted">
                  No GitHub credential connected yet —{" "}
                  <a href="/connections/github" className="underline">
                    connect one
                  </a>{" "}
                  first.
                </p>
              )}
            </div>
          </div>

          <div>
            <label className="label">LLM credential</label>
            <select
              className="input"
              value={llmCredentialId}
              onChange={(e) => setLlmCredentialId(e.target.value)}
            >
              <option value="">Use account default</option>
              {llmCreds.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label} ({c.provider}/{c.model})
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="card space-y-2">
          <label className="label">Connectors (optional — off by default, revisable later)</label>
          {connectors.length === 0 && (
            <p className="text-sm text-muted">
              No connectors on your account yet — you can add one from Connections any time.
            </p>
          )}
          {connectors.map((c) => (
            <label key={c.id} className="flex items-center gap-2 text-sm border border-line rounded-md p-2">
              <input
                type="checkbox"
                checked={connectorIds.includes(c.id)}
                onChange={(e) =>
                  setConnectorIds((prev) =>
                    e.target.checked ? [...prev, c.id] : prev.filter((id) => id !== c.id)
                  )
                }
              />
              {c.name}
            </label>
          ))}
        </div>
      )}

      {step === 4 && (
        <div className="card space-y-2 text-sm">
          <p>
            <span className="text-muted">Name:</span> {name}
          </p>
          <p>
            <span className="text-muted">Repository:</span>{" "}
            {mode === "scratch"
              ? "none (from scratch)"
              : mode === "import"
              ? githubRepo
              : `new repo "${newRepoName}" (${newRepoPrivate ? "private" : "public"})`}
          </p>
          <p>
            <span className="text-muted">LLM credential:</span>{" "}
            {llmCreds.find((c) => c.id === llmCredentialId)?.label ?? "account default"}
          </p>
          <p>
            <span className="text-muted">Connectors:</span>{" "}
            {connectorIds.length === 0 ? "none" : connectorIds.length}
          </p>
        </div>
      )}

      <div className="flex justify-between mt-4">
        <button className="btn-default" disabled={step === 1 || busy} onClick={() => setStep((s) => s - 1)}>
          Back
        </button>
        {step < 4 ? (
          <button className="btn-primary" disabled={!canAdvanceFrom(step)} onClick={() => setStep((s) => s + 1)}>
            Next
          </button>
        ) : (
          <button className="btn-primary" disabled={busy} onClick={execute}>
            {busy ? "Creating…" : "Create project"}
          </button>
        )}
      </div>
    </div>
  );
}

function CredentialSelect({
  creds,
  value,
  onChange,
}: {
  creds: GithubCredential[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Select a GitHub credential…</option>
      {creds.map((c) => (
        <option key={c.id} value={c.id}>
          {c.label}
        </option>
      ))}
    </select>
  );
}

export default function NewProjectPage() {
  return (
    <AuthGuard>
      <NavBar />
      <main className="max-w-5xl mx-auto px-4 py-6">
        <NewProjectWizard />
      </main>
    </AuthGuard>
  );
}
