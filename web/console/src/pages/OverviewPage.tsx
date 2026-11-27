import { useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  Boxes,
  CircleCheck,
  Clock3,
  FolderArchive,
  Play,
  SearchCheck,
  Square,
  Users
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { formatDuration, formatTimestamp, humanize } from "../lib/format";
import type { ReviewRun } from "../lib/types";
import { useAuth } from "../state/AuthProvider";
import { useConsole } from "../state/ConsoleProvider";
import { useToast } from "../state/ToastProvider";
import { ArtifactLinks } from "../components/ArtifactLinks";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { Surface } from "../components/Surface";

export function OverviewPage() {
  const { overview, error, loading, refresh } = useConsole();
  const { token } = useAuth();
  const { pushToast } = useToast();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<string | null>(null);
  const [reviewRuns, setReviewRuns] = useState<ReviewRun[]>([]);

  useEffect(() => {
    if (!token) {
      setReviewRuns([]);
      return;
    }
    let active = true;
    api
      .reviewRuns(token)
      .then((response) => {
        if (active) {
          setReviewRuns(response.runs ?? []);
        }
      })
      .catch(() => {
        if (active) {
          setReviewRuns([]);
        }
      });
    return () => {
      active = false;
    };
  }, [token]);

  if (loading && !overview) {
    return <div className="page-skeleton" aria-label="Loading overview" />;
  }

  if (error && !overview) {
    return (
      <EmptyState
        title="Console data unavailable"
        description="The local operations API did not respond."
        action={
          <Button onClick={() => void refresh()} icon={<ArrowRight size={16} />}>
            Retry
          </Button>
        }
      />
    );
  }

  if (!overview) {
    return null;
  }

  const run = overview.demo;
  const workers = overview.workers ?? [];
  const activeWorkers = workers.filter(
    (worker) => worker.state !== "offline"
  ).length;
  const pendingReviews = reviewRuns.reduce(
    (total, item) => total + (item.review_summary?.pending ?? 0),
    0
  );
  const evidenceCount = overview.history.reduce(
    (total, item) =>
      total +
      item.artifacts.filter((artifact) => artifact.name.endsWith(".zip"))
        .length,
    0
  );
  const runLabel =
    run.state === "idle"
      ? "No active run"
      : run.kind === "upload"
        ? run.source_name || "Uploaded input"
        : "Invoice reconciliation demo";

  const execute = async (
    action: "start" | "cancel" | "bundle",
    callback: () => Promise<unknown>,
    success: string
  ) => {
    setBusy(action);
    try {
      await callback();
      pushToast(success, "success");
      await refresh();
      if (action === "start") {
        navigate("/run");
      }
    } catch (caught) {
      pushToast(
        caught instanceof Error ? caught.message : "Action failed",
        "error"
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="page-stack">
      <PageHeader
        title="Operations overview"
        description="Observe runs, evidence, and operator work from one auditable surface."
        actions={
          <Button
            variant="primary"
            icon={<Play size={16} />}
            onClick={() => navigate("/new")}
          >
            New run
          </Button>
        }
      />

      <section className="metric-grid" aria-label="Operations summary">
        <div className="metric">
          <span className="metric-icon metric-icon-blue">
            <Users size={18} />
          </span>
          <div>
            <strong>{activeWorkers}</strong>
            <span>Active workers</span>
          </div>
        </div>
        <div className="metric">
          <span className="metric-icon metric-icon-green">
            <Activity size={18} />
          </span>
          <div>
            <strong>{humanize(run.state)}</strong>
            <span>Current run</span>
          </div>
        </div>
        <div className="metric">
          <span className="metric-icon metric-icon-amber">
            <SearchCheck size={18} />
          </span>
          <div>
            <strong>{pendingReviews}</strong>
            <span>Pending reviews</span>
          </div>
        </div>
        <div className="metric">
          <span className="metric-icon metric-icon-slate">
            <FolderArchive size={18} />
          </span>
          <div>
            <strong>{evidenceCount}</strong>
            <span>Evidence bundles</span>
          </div>
        </div>
      </section>

      <Surface
        className="run-command"
        header={
          <>
            <div>
              <span className="section-kicker">Current execution</span>
              <h2>{runLabel}</h2>
            </div>
            <StatusBadge status={run.state} />
          </>
        }
        footer={
          <div className="run-command-actions">
            <Button
              variant="primary"
              disabled={run.state === "running" || busy !== null}
              icon={<Play size={16} />}
              onClick={() =>
                void execute("start", api.startDemo, "Invoice demo started.")
              }
            >
              Run invoice demo
            </Button>
            <Button
              variant="danger"
              disabled={run.state !== "running" || busy !== null}
              icon={<Square size={15} />}
              onClick={() =>
                void execute("cancel", api.cancelRun, "Run cancellation requested.")
              }
            >
              Stop run
            </Button>
            <Button
              disabled={
                run.state === "running" ||
                run.state === "idle" ||
                busy !== null
              }
              icon={<Boxes size={16} />}
              onClick={() =>
                void execute(
                  "bundle",
                  api.createBundle,
                  "Evidence bundle created."
                )
              }
            >
              Create evidence bundle
            </Button>
            <Link className="text-link run-detail-link" to="/run">
              Open run monitor
              <ArrowRight size={15} />
            </Link>
          </div>
        }
      >
        <div className="run-command-grid">
          <div className="run-facts">
            <div>
              <Clock3 size={16} />
              <span>
                Elapsed {formatDuration(run.elapsed_seconds)}
              </span>
            </div>
            <div>
              <Activity size={16} />
              <span>
                {run.kind ? humanize(run.kind) : "No active execution"}
              </span>
            </div>
          </div>
          <ArtifactLinks artifacts={run.artifacts} />
        </div>
        {run.log_tail.length ? (
          <pre className="terminal-panel">
            {run.log_tail.slice(-12).join("\n")}
          </pre>
        ) : (
          <div className="command-empty">
            Start the built-in scenario to stream execution output here.
          </div>
        )}
      </Surface>

      <div className="split-grid">
        <Surface
          header={
            <>
              <div>
                <span className="section-kicker">Execution fleet</span>
                <h2>Workers</h2>
              </div>
              <span className="surface-count">{workers.length}</span>
            </>
          }
        >
          {workers.length ? (
            <div className="worker-list">
              {workers.map((worker) => (
                <div className="worker-row" key={worker.worker_id}>
                  <div className="worker-identity">
                    <span className="worker-icon">
                      <CircleCheck size={17} />
                    </span>
                    <div>
                      <strong>{worker.worker_id}</strong>
                      <span>
                        {worker.hostname}:{worker.pid}
                      </span>
                    </div>
                  </div>
                  <div className="worker-meta">
                    <StatusBadge status={worker.state} />
                    <span>{worker.labels.join(" · ") || "No labels"}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No worker online"
              description="Start the local queue worker before accepting GUI jobs."
            />
          )}
        </Surface>

        <Surface
          header={
            <>
              <div>
                <span className="section-kicker">Operator workflow</span>
                <h2>Review queue</h2>
              </div>
              <ClipboardMini pending={pendingReviews} />
            </>
          }
          footer={
            <Link className="text-link" to="/reviews">
              Open reviews <ArrowRight size={15} />
            </Link>
          }
        >
          {!token ? (
            <EmptyState
              title="Operator authentication required"
              description="Connect with the local access token to inspect and resolve reconciliation differences."
              action={
                <Button onClick={() => navigate("/reviews")}>
                  Connect operator
                </Button>
              }
            />
          ) : reviewRuns.length ? (
            <div className="review-preview-list">
              {reviewRuns.slice(0, 4).map((item) => (
                <button
                  type="button"
                  className="review-preview-row"
                  key={item.run}
                  onClick={() =>
                    navigate(`/reviews?run=${encodeURIComponent(item.run)}`)
                  }
                >
                  <span>
                    <strong>{item.run}</strong>
                    <small>{formatTimestamp(item.updated_at)}</small>
                  </span>
                  <span>
                    {item.closed ? (
                      <StatusBadge status="closed" />
                    ) : (
                      <span className="review-count">
                        {item.review_summary?.pending ?? 0} pending
                      </span>
                    )}
                    <ArrowRight size={16} />
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyState
              title="No reconciliation reviews"
              description="Completed invoice runs with differences will appear here."
            />
          )}
        </Surface>
      </div>

      <div className="split-grid split-grid-wide">
        <Surface
          className="table-surface"
          header={
            <>
              <div>
                <span className="section-kicker">Recent activity</span>
                <h2>Run history</h2>
              </div>
              <Link className="text-link" to="/run">
                Run monitor <ArrowRight size={15} />
              </Link>
            </>
          }
        >
          {overview.history.length ? (
            <div className="table-scroll">
              <table className="data-table run-history-table">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Source</th>
                    <th>State</th>
                    <th>Started</th>
                    <th>Artifacts</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.history.map((item, index) => (
                    <tr
                      key={`${item.run_url}-${index}`}
                      onClick={() =>
                        navigate(
                          `/run?name=${encodeURIComponent(
                            item.output_dir?.split("/").pop() ?? ""
                          )}`
                        )
                      }
                    >
                      <td>
                        <strong className="mono">
                          {item.output_dir?.split("/").pop() || "Run"}
                        </strong>
                      </td>
                      <td>{item.source_name || humanize(item.kind)}</td>
                      <td>
                        <StatusBadge status={item.state || "unknown"} />
                      </td>
                      <td>{formatTimestamp(item.started_at)}</td>
                      <td>{item.artifacts.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              title="No runs yet"
              description="Start the invoice demo to create the first auditable run."
              action={
                <Button variant="primary" onClick={() => navigate("/new")}>
                  New run
                </Button>
              }
            />
          )}
        </Surface>

        <Surface
          className="table-surface"
          header={
            <>
              <div>
                <span className="section-kicker">Evidence index</span>
                <h2>Recent reports</h2>
              </div>
              <span className="surface-count">{overview.reports.length}</span>
            </>
          }
        >
          {overview.reports.length ? (
            <div className="table-scroll">
              <table className="data-table reports-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>State</th>
                    <th>Duration</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {overview.reports.slice(0, 8).map((report) => (
                    <tr key={report.url}>
                      <td>
                        <strong>{report.name}</strong>
                        <small>{humanize(report.type)}</small>
                      </td>
                      <td>
                        <StatusBadge status={report.status} />
                      </td>
                      <td>{formatDuration(report.duration_seconds)}</td>
                      <td>
                        <a
                          className="table-action"
                          href={report.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          Open report
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              title="No reports indexed"
              description="Reports are added after a task or reconciliation run completes."
            />
          )}
        </Surface>
      </div>
    </div>
  );
}

function ClipboardMini({ pending }: { pending: number }) {
  return (
    <span className="review-mini">
      <SearchCheck size={15} />
      {pending} pending
    </span>
  );
}
