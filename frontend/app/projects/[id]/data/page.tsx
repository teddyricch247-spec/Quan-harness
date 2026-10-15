"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import PageFrame from "@/components/PageFrame";
import ErrorBanner from "@/components/ErrorBanner";
import { apiFetch, ApiError } from "@/lib/api";
import { DataFlowsOut } from "@/lib/types";

/**
 * Phase 5.6 (§23.10): "be explicit and honest in-product about exactly what leaves the workspace and when." The statement
 * itself is written once, in the backend (app/services/data_flows.py), and made specific to this project (which model,
 * which repository, which connectors). This page only shows it — and says plainly whether the agent can look at its own
 * work, and why not when it can't.
 */
export default function ProjectDataFlowsPage() {
  const params = useParams<{ id: string }>();
  const [data, setData] = useState<DataFlowsOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<DataFlowsOut>(`/projects/${params.id}/data-flows`).then(setData).catch((e: ApiError) => setError(e.message));
  }, [params.id]);

  return (
    <PageFrame title="What leaves this workspace" back={`/projects/${params.id}/settings`}>
      <div className="max-w-lg space-y-4">
        <ErrorBanner message={error} />
        {!data && !error && <p className="text-sm text-muted">Loading…</p>}
        {data && (
          <>
            <section className="card space-y-1">
              <p className="font-medium text-sm">The agent&apos;s browser</p>
              <p className="text-sm">{data.agent_browser.available ? "On: the agent can take screenshots of this project\u2019s running app." : data.agent_browser.reason}</p>
            </section>
            {data.flows.map((flow) => (
              <section key={flow.id} className="card space-y-2">
                <p className="font-medium text-sm">{flow.title}</p>
                <p className="text-sm">
                  <span className="text-muted">When: </span>
                  {flow.when}
                </p>
                <p className="text-sm">
                  <span className="text-muted">To: </span>
                  {flow.where}
                </p>
                <div>
                  <p className="text-xs text-muted">What is sent</p>
                  <ul className="list-disc pl-5 text-sm space-y-0.5">
                    {flow.sends.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
                {flow.never.length > 0 && (
                  <div>
                    <p className="text-xs text-muted">What is never sent</p>
                    <ul className="list-disc pl-5 text-sm space-y-0.5">
                      {flow.never.map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {flow.caveat && <p className="text-xs text-muted">{flow.caveat}</p>}
              </section>
            ))}
          </>
        )}
      </div>
    </PageFrame>
  );
}
