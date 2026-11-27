import { useEffect, useState } from "react";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Boxes,
  Clock3,
  FileJson,
  FolderArchive,
  Play,
  RefreshCw,
  Square,
  TerminalSquare
} from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { formatDuration, formatTimestamp, humanize } from "../lib/format";
import { usePolling } from "../lib/hooks";
import type {
  HistoryEntry,
  ReconciliationPayload
} from "../lib/types";
import { useConsole } from "../state/ConsoleProvider";
import { useToast } from "../state/ToastProvider";
import { ArtifactLinks } from "../components/ArtifactLinks";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { Surface } from "../components/Surface";

function runName(entry: HistoryEntry): string {
  return entry.output_dir?.split("/").pop() || "Run";
}

export function RunPage() {
  const { overview, refresh } = useConsole();
  const live = usePolling(api.demoStatus, 2000, "demo");
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { pushToast } = useToast();
  const [selectedReport, setSelectedReport] =
    useState<ReconciliationPayload | null>(null);
  const [selectedLog, setSelectedLog] = useState("");
  const [selectedLoading, setSelectedLoading] = useState(false);
  const selectedName = searchParams.get("name");
  const selectedHistory = overview?.history.find(
    (entry) => runName(entry) === selectedName
  );
  const reportArtifact = selectedHistory?.artifacts.find(
    (artifact) => artifact.name === "reconciliation.json"
  );
  const logArtifact = selectedHistory?.artifacts.find(
    (artifact) => artifact.name === "run.log"
  );
  const liveStatus = live.data ?? overview?.demo;
  const viewingHistory = Boolean(selectedName);
  const run = viewingHistory ? selectedHistory : liveStatus;
  const runState = run?.state ?? "idle";
  const artifacts = run?.artifacts ?? [];
  const logLines = viewingHistory
    ? selectedLog.split("\n").filter(Boolean)
    : liveStatus?.log_tail ?? [];
  const displayName = viewingHistory
    ? selectedName || "Historical run"
    : runState === "idle"
      ? "Live run monitor"
      : run?.source_name || humanize(run?.kind || "Invoice reconciliation");
  const summary =
    selectedReport?.reconciliation?.summary ?? selectedReport?.summary;
  const results =
    selectedReport?.reconciliation?.results ?? selectedReport?.results ?? [];
  const orderedResults = [...results].sort((left, right) => {
    const leftMatched = left.status === "matched" ? 1 : 0;
    const rightMatched = right.status === "matched" ? 1 : 0;
    return leftMatched - rightMatched;
  });

  useEffect(() => {
    if (!viewingHistory || !reportArtifact) {
      setSelectedReport(null);
      return;
    }
    let active = true;
    setSelectedLoading(true);
    api
      .reconciliation(reportArtifact.url)
      .then((payload) => {
        if (active) {
          setSelectedReport(payload);
        }
      })
      .catch(() => {
        if (active) {
          setSelectedReport(null);
        }
      })
      .finally(() => {
        if (active) {
          setSelectedLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [reportArtifact?.url, viewingHistory]);

  useEffect(() => {
    if (!viewingHistory || !logArtifact) {
      setSelectedLog("");
      return;
    }
    let active = true;
    fetch(logArtifact.url)
      .then((response) => (response.ok ? response.text() : ""))
      .then((content) => {
        if (active) {
          setSelectedLog(content);
        }
      })
      .catch(() => {
        if (active) {
          setSelectedLog("");
        }
      });
    return () => {
      active = false;
    };
  }, [logArtifact?.url, viewingHistory]);

  const startNewRun = async () => {
    try {
      await api.startDemo();
      await refresh();
      pushToast("Invoice demo started.", "success");
      navigate("/run");
    } catch (caught) {
      pushToast(
        caught instanceof Error ? caught.message : "Could not start run.",
        "error"
      );
    }
  };

  const stopRun = async () => {
    try {
      await api.cancelRun();
      await Promise.all([refresh(), live.refresh()]);
      pushToast("Run cancellation requested.", "success");
    } catch (caught) {
      pushToast(
        caught instanceof Error ? caught.message : "Could not stop run.",
        "error"
      );
    }
  };

  const createBundle = async () => {
    try {
      await api.createBundle();
      await Promise.all([refresh(), live.refresh()]);
      pushToast("Evidence bundle created.", "success");
    } catch (caught) {
      pushToast(
        caught instanceof Error ? caught.message : "Could not create bundle.",
        "error"
      );
    }
  };

  if (!run && !overview) {
    return <div className="page-skeleton" aria-label="Loading run monitor" />;
  }

  return (
    <div className="page-stack">
      <PageHeader
        title="Run monitor"
        description="Follow execution output and inspect evidence as soon as it is written."
        actions={
          <Button
            icon={<RefreshCw size={16} />}
            onClick={() => {
              void Promise.all([refresh(), live.refresh()]);
            }}
          >
            Refresh
          </Button>
        }
      />

      <div className="run-monitor-layout">
        <div className="page-stack">
          <Surface
            className="run-header-surface"
            header={
              <>
                <div className="run-title">
                  {viewingHistory ? (
                    <Link className="icon-back" to="/run">
                      <ArrowLeft size={17} />
                    </Link>
                  ) : null}
                  <div>
                    <span className="section-kicker">
                      {viewingHistory ? "Historical run" : "Current execution"}
                    </span>
                    <h2>{displayName}</h2>
                  </div>
                </div>
                <StatusBadge status={String(runState)} />
              </>
            }
          >
            <div className="run-summary-strip">
              <div>
                <Clock3 size={16} />
                <span>Elapsed</span>
                <strong>
                  {formatDuration(
                    viewingHistory ? null : liveStatus?.elapsed_seconds
                  )}
                </strong>
              </div>
              <div>
                <Activity size={16} />
                <span>Kind</span>
                <strong>{humanize(run?.kind)}</strong>
              </div>
              <div>
                <FolderArchive size={16} />
                <span>Artifacts</span>
                <strong>{artifacts.length}</strong>
              </div>
              <div>
                <TerminalSquare size={16} />
                <span>Output lines</span>
                <strong>{logLines.length}</strong>
              </div>
            </div>
            {!viewingHistory ? (
              <div className="run-actions">
                <Button
                  variant="primary"
                  icon={<Play size={16} />}
                  disabled={runState === "running"}
                  onClick={() => void startNewRun()}
                >
                  Start demo
                </Button>
                <Button
                  variant="danger"
                  icon={<Square size={15} />}
                  disabled={runState !== "running"}
                  onClick={() => void stopRun()}
                >
                  Stop run
                </Button>
                <Button
                  icon={<Boxes size={16} />}
                  disabled={
                    runState === "running" || runState === "idle"
                  }
                  onClick={() => void createBundle()}
                >
                  Create evidence bundle
                </Button>
              </div>
            ) : null}
          </Surface>

          <Surface
            className="terminal-surface"
            header={
              <>
                <div>
                  <span className="section-kicker">Execution stream</span>
                  <h2>Output</h2>
                </div>
                <span className="terminal-status">
                  <span
                    className={
                      runState === "running"
                        ? "live-dot"
                        : "live-dot live-dot-muted"
                    }
                  />
                  {humanize(runState)}
                </span>
              </>
            }
          >
            {logLines.length ? (
              <pre className="terminal-panel terminal-panel-large">
                {logLines.join("\n")}
              </pre>
            ) : (
              <div className="terminal-empty">
                Execution output will stream here.
              </div>
            )}
          </Surface>

          <Surface
            className="table-surface"
            header={
              <>
                <div>
                  <span className="section-kicker">Deterministic result</span>
                  <h2>Reconciliation summary</h2>
                </div>
                {selectedLoading ? (
                  <span className="muted">Loading report…</span>
                ) : null}
              </>
            }
          >
            {summary ? (
              <>
                <div className="summary-counts">
                  <div>
                    <strong>{summary.total}</strong>
                    <span>Invoices</span>
                  </div>
                  <div>
                    <strong>{summary.by_status.matched ?? 0}</strong>
                    <span>Matched</span>
                  </div>
                  <div>
                    <strong>
                      {summary.total - (summary.by_status.matched ?? 0)}
                    </strong>
                    <span>Differences</span>
                  </div>
                </div>
                {results.length ? (
                  <div className="table-scroll">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Invoice</th>
                          <th>Result</th>
                          <th>Detail</th>
                        </tr>
                      </thead>
                      <tbody>
                        {orderedResults.slice(0, 10).map((item) => (
                          <tr key={item.invoice_id}>
                            <td className="mono">{item.invoice_id}</td>
                            <td>
                              <StatusBadge status={item.status} />
                            </td>
                            <td>
                              {item.error ||
                                item.differences?.join("; ") ||
                                "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </>
            ) : (
              <EmptyState
                title="No reconciliation summary yet"
                description={
                  viewingHistory
                    ? "This run does not expose a reconciliation report."
                    : "The summary appears after the browser run finishes."
                }
              />
            )}
          </Surface>
        </div>

        <aside className="run-sidebar">
          <Surface
            header={
              <div>
                <span className="section-kicker">Evidence</span>
                <h2>Artifacts</h2>
              </div>
            }
          >
            <ArtifactLinks artifacts={artifacts} />
          </Surface>

          <Surface
            header={
              <div>
                <span className="section-kicker">Run ledger</span>
                <h2>History</h2>
              </div>
            }
          >
            {overview?.history.length ? (
              <div className="run-history-list">
                {overview.history.map((entry) => (
                  <button
                    className={
                      runName(entry) === selectedName
                        ? "run-history-item is-active"
                        : "run-history-item"
                    }
                    key={entry.run_url}
                    type="button"
                    onClick={() =>
                      navigate(
                        `/run?name=${encodeURIComponent(runName(entry))}`
                      )
                    }
                  >
                    <span>
                      <strong className="mono">{runName(entry)}</strong>
                      <small>{formatTimestamp(entry.started_at)}</small>
                    </span>
                    <span>
                      <StatusBadge status={entry.state || "unknown"} subtle />
                      <ArrowRight size={15} />
                    </span>
                  </button>
                ))}
                <Link className="text-link" to="/run">
                  Return to live run
                </Link>
              </div>
            ) : (
              <EmptyState
                title="No run history"
                description="Completed console runs will be indexed here."
              />
            )}
          </Surface>

          <Surface
            className="compact-surface"
            header={
              <div>
                <span className="section-kicker">Report source</span>
                <h2>Expected input</h2>
              </div>
            }
          >
            <div className="source-file">
              <FileJson size={19} />
              <span>
                {selectedReport?.expected_csv ||
                  "scenarios/invoice_reconciliation/data/input_invoices.csv"}
              </span>
            </div>
          </Surface>
        </aside>
      </div>
    </div>
  );
}
