import {
  useCallback,
  useDeferredValue,
  useEffect,
  useState,
  type FormEvent
} from "react";
import {
  Check,
  CheckCheck,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  LockKeyhole,
  RefreshCw,
  Search,
  ShieldCheck,
  X
} from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { formatTimestamp, humanize } from "../lib/format";
import type {
  ReviewRun,
  ReviewState,
  ReviewStatus
} from "../lib/types";
import { useAuth } from "../state/AuthProvider";
import { useToast } from "../state/ToastProvider";
import { Button } from "../components/Button";
import { EmptyState } from "../components/EmptyState";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { Surface } from "../components/Surface";

interface ReviewDraft {
  status: ReviewStatus;
  note: string;
}

const reviewStatuses: Array<{ value: ReviewStatus; label: string }> = [
  { value: "pending", label: "Pending" },
  { value: "confirmed", label: "Confirmed" },
  { value: "false_positive", label: "False positive" }
];

export function ReviewsPage() {
  const {
    token,
    session,
    loading: authLoading,
    authenticate
  } = useAuth();
  const { pushToast } = useToast();
  const [searchParams] = useSearchParams();
  const requestedRun = searchParams.get("run") ?? "";
  const [tokenInput, setTokenInput] = useState("");
  const [runs, setRuns] = useState<ReviewRun[]>([]);
  const [selectedRun, setSelectedRun] = useState(requestedRun);
  const [state, setState] = useState<ReviewState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, ReviewDraft>>({});
  const [batchStatus, setBatchStatus] =
    useState<ReviewStatus>("confirmed");
  const [batchNote, setBatchNote] = useState("");
  const [closeOpen, setCloseOpen] = useState(false);
  const [closeNote, setCloseNote] = useState("");
  const [actionBusy, setActionBusy] = useState("");

  const applyState = (nextState: ReviewState) => {
    setState(nextState);
    setDrafts(
      Object.fromEntries(
        nextState.results.map((result) => [
          result.invoice_id,
          {
            status: result.review?.status ?? "pending",
            note: result.review?.note ?? ""
          }
        ])
      )
    );
    setSelectedIds(new Set());
  };

  const loadRuns = useCallback(
    async (preferredRun?: string) => {
      if (!token) {
        return;
      }
      try {
        const response = await api.reviewRuns(token);
        setRuns(response.runs ?? []);
        if (!response.runs?.length) {
          setSelectedRun("");
          setState(null);
          return;
        }
        const nextRun =
          preferredRun ||
          selectedRun ||
          requestedRun ||
          response.runs[0].run;
        setSelectedRun(
          response.runs.some((item) => item.run === nextRun)
            ? nextRun
            : response.runs[0].run
        );
      } catch (caught) {
        setError(
          caught instanceof Error ? caught.message : "Could not load reviews."
        );
      }
    },
    [requestedRun, selectedRun, token]
  );

  useEffect(() => {
    if (token && session) {
      void loadRuns(requestedRun || undefined);
    }
  }, [loadRuns, requestedRun, session, token]);

  useEffect(() => {
    if (!token || !selectedRun) {
      setState(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError("");
    api
      .reviewState(token, selectedRun)
      .then((response) => {
        if (active) {
          applyState(response);
        }
      })
      .catch((caught) => {
        if (active) {
          setError(
            caught instanceof Error
              ? caught.message
              : "Could not load review state."
          );
          setState(null);
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [selectedRun, token]);

  const connect = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const nextSession = await authenticate(tokenInput);
      pushToast(`Connected as ${nextSession.operator}.`, "success");
      setTokenInput("");
    } catch (caught) {
      pushToast(
        caught instanceof Error ? caught.message : "Authentication failed.",
        "error"
      );
    }
  };

  const saveOne = async (invoiceId: string) => {
    if (!token || !state) {
      return;
    }
    const draft = drafts[invoiceId];
    setActionBusy(invoiceId);
    try {
      const next = await api.saveReview(token, {
        run: state.run,
        invoice_id: invoiceId,
        status: draft.status,
        note: draft.note
      });
      applyState(next);
      await loadRuns(state.run);
      pushToast(`${invoiceId} review saved.`, "success");
    } catch (caught) {
      pushToast(
        caught instanceof Error ? caught.message : "Review save failed.",
        "error"
      );
    } finally {
      setActionBusy("");
    }
  };

  const saveBatch = async () => {
    if (!token || !state || !selectedIds.size) {
      pushToast("Select at least one difference.", "error");
      return;
    }
    setActionBusy("batch");
    try {
      const next = await api.saveReviews(token, {
        run: state.run,
        invoice_ids: [...selectedIds],
        status: batchStatus,
        note: batchNote
      });
      applyState(next);
      setBatchNote("");
      await loadRuns(state.run);
      pushToast(
        `${selectedIds.size} review decisions saved.`,
        "success"
      );
    } catch (caught) {
      pushToast(
        caught instanceof Error ? caught.message : "Batch review failed.",
        "error"
      );
    } finally {
      setActionBusy("");
    }
  };

  const closeReview = async () => {
    if (!token || !state || !state.can_close) {
      return;
    }
    setActionBusy("close");
    try {
      const next = await api.closeReview(token, state.run, closeNote);
      applyState(next);
      setCloseOpen(false);
      setCloseNote("");
      await loadRuns(state.run);
      pushToast("Review run closed with an audit fingerprint.", "success");
    } catch (caught) {
      pushToast(
        caught instanceof Error ? caught.message : "Could not close run.",
        "error"
      );
    } finally {
      setActionBusy("");
    }
  };

  if (!token && !authLoading) {
    return (
      <div className="page-stack">
        <PageHeader
          title="Human reviews"
          description="Resolve reconciliation differences with authenticated, hash-chained decisions."
        />
        <div className="auth-layout">
          <Surface className="auth-surface">
            <div className="auth-lock">
              <LockKeyhole size={23} />
            </div>
            <h2>Connect an operator</h2>
            <p>
              Enter the access token from{" "}
              <code>.opskestrel-console-token</code>. The token stays in this
              browser tab.
            </p>
            <form onSubmit={(event) => void connect(event)}>
              <label className="field">
                <span>Operator access token</span>
                <input
                  type="password"
                  autoComplete="off"
                  value={tokenInput}
                  onChange={(event) => setTokenInput(event.target.value)}
                  placeholder="Paste local operator token"
                />
              </label>
              <Button
                className="full-width"
                variant="primary"
                type="submit"
                disabled={authLoading || !tokenInput.trim()}
              >
                {authLoading ? "Connecting…" : "Connect operator"}
              </Button>
            </form>
          </Surface>
          <div className="auth-notes">
            <div>
              <ShieldCheck size={19} />
              <strong>Server-enforced roles</strong>
              <p>
                Viewer, reviewer, and admin actions are checked by the Python
                console server.
              </p>
            </div>
            <div>
              <ClipboardCheck size={19} />
              <strong>Immutable audit trail</strong>
              <p>
                Every decision is appended to a hash-chained review log before
                reports are refreshed.
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const filteredResults =
    state?.results.filter((item) =>
      `${item.invoice_id} ${item.status}`
        .toLowerCase()
        .includes(deferredSearch.toLowerCase())
    ) ?? [];
  const allVisibleSelected =
    filteredResults.length > 0 &&
    filteredResults.every((item) => selectedIds.has(item.invoice_id));
  const pending = state?.review_summary.pending ?? 0;

  return (
    <div className="page-stack">
      <PageHeader
        title="Human reviews"
        description="Resolve reconciliation differences with authenticated, hash-chained decisions."
        actions={
          session ? (
            <span className="operator-chip">
              <ShieldCheck size={15} />
              {session.operator} · {session.role}
            </span>
          ) : null
        }
      />

      <Surface className="review-toolbar-surface">
        <div className="review-toolbar">
          <label className="field review-run-field">
            <span>Reconciliation run</span>
            <select
              value={selectedRun}
              onChange={(event) => setSelectedRun(event.target.value)}
            >
              {runs.length ? null : (
                <option value="">No review runs</option>
              )}
              {runs.map((run) => (
                <option key={run.run} value={run.run}>
                  {run.run}
                  {run.closed
                    ? " · closed"
                    : ` · ${run.review_summary?.pending ?? 0} pending`}
                </option>
              ))}
            </select>
          </label>
          <Button
            icon={<RefreshCw size={16} />}
            onClick={() => void loadRuns(selectedRun)}
          >
            Refresh
          </Button>
        </div>
      </Surface>

      {error ? (
        <div className="error-banner">
          <CircleAlert size={19} />
          <span>{error}</span>
        </div>
      ) : null}

      {loading && !state ? (
        <div className="page-skeleton" aria-label="Loading reviews" />
      ) : state ? (
        <>
          <section className="review-metrics">
            <div>
              <span>Pending</span>
              <strong>{state.review_summary.pending}</strong>
            </div>
            <div>
              <span>Confirmed</span>
              <strong>{state.review_summary.confirmed}</strong>
            </div>
            <div>
              <span>False positive</span>
              <strong>{state.review_summary.false_positive}</strong>
            </div>
            <div>
              <span>Audit events</span>
              <strong>{state.audit_events.length}</strong>
            </div>
          </section>

          {state.closure ? (
            <div className="closure-banner">
              <CheckCheck size={20} />
              <div>
                <strong>Review closed by {state.closure.closed_by}</strong>
                <span>{formatTimestamp(state.closure.closed_at)}</span>
                {state.closure.note ? <p>{state.closure.note}</p> : null}
              </div>
            </div>
          ) : null}

          <Surface
            className="table-surface review-table-surface"
            header={
              <>
                <div>
                  <span className="section-kicker">Difference queue</span>
                  <h2>{state.run}</h2>
                </div>
                <label className="search-field">
                  <Search size={16} />
                  <input
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    placeholder="Search invoice or result"
                  />
                </label>
              </>
            }
            footer={
              state.closure ? null : (
                <div className="batch-review-bar">
                  <select
                    value={batchStatus}
                    onChange={(event) =>
                      setBatchStatus(event.target.value as ReviewStatus)
                    }
                  >
                    {reviewStatuses.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <input
                    value={batchNote}
                    onChange={(event) => setBatchNote(event.target.value)}
                    placeholder="Batch note"
                  />
                  <Button
                    icon={<Check size={16} />}
                    disabled={!selectedIds.size || actionBusy !== ""}
                    onClick={() => void saveBatch()}
                  >
                    Save selected ({selectedIds.size})
                  </Button>
                  <Button
                    variant={state.can_close ? "primary" : "secondary"}
                    disabled={!state.can_close || actionBusy !== ""}
                    onClick={() => setCloseOpen(true)}
                  >
                    Close review
                  </Button>
                </div>
              )
            }
          >
            <div className="table-scroll">
              <table className="data-table review-table">
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        checked={allVisibleSelected}
                        aria-label="Select all visible differences"
                        onChange={(event) => {
                          const next = new Set(selectedIds);
                          filteredResults.forEach((item) => {
                            if (event.target.checked) {
                              next.add(item.invoice_id);
                            } else {
                              next.delete(item.invoice_id);
                            }
                          });
                          setSelectedIds(next);
                        }}
                      />
                    </th>
                    <th>Invoice</th>
                    <th>Algorithm result</th>
                    <th>Decision</th>
                    <th>Note</th>
                    <th>Reviewer</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filteredResults.map((item) => {
                    const draft = drafts[item.invoice_id] ?? {
                      status: "pending",
                      note: ""
                    };
                    return (
                      <tr key={item.invoice_id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={selectedIds.has(item.invoice_id)}
                            disabled={Boolean(state.closure)}
                            aria-label={`Select ${item.invoice_id}`}
                            onChange={(event) => {
                              const next = new Set(selectedIds);
                              if (event.target.checked) {
                                next.add(item.invoice_id);
                              } else {
                                next.delete(item.invoice_id);
                              }
                              setSelectedIds(next);
                            }}
                          />
                        </td>
                        <td>
                          <strong className="mono">{item.invoice_id}</strong>
                        </td>
                        <td>
                          <StatusBadge status={item.status} />
                        </td>
                        <td>
                          <select
                            value={draft.status}
                            disabled={Boolean(state.closure)}
                            onChange={(event) =>
                              setDrafts((current) => ({
                                ...current,
                                [item.invoice_id]: {
                                  ...draft,
                                  status: event.target.value as ReviewStatus
                                }
                              }))
                            }
                          >
                            {reviewStatuses.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <input
                            value={draft.note}
                            disabled={Boolean(state.closure)}
                            placeholder="Add review note"
                            onChange={(event) =>
                              setDrafts((current) => ({
                                ...current,
                                [item.invoice_id]: {
                                  ...draft,
                                  note: event.target.value
                                }
                              }))
                            }
                          />
                        </td>
                        <td>
                          {item.review ? (
                            <>
                              <strong>{item.review.reviewer || "—"}</strong>
                              <small>
                                {formatTimestamp(item.review.updated_at)}
                              </small>
                            </>
                          ) : (
                            <span className="muted">Not reviewed</span>
                          )}
                        </td>
                        <td>
                          {state.closure ? (
                            <span className="muted">Closed</span>
                          ) : (
                            <Button
                              size="compact"
                              disabled={actionBusy === item.invoice_id}
                              onClick={() => void saveOne(item.invoice_id)}
                            >
                              {actionBusy === item.invoice_id
                                ? "Saving…"
                                : "Save"}
                            </Button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {!filteredResults.length ? (
              <EmptyState
                title="No differences found"
                description={
                  search
                    ? "No review row matches the current search."
                    : "This run has no reconciliation differences."
                }
              />
            ) : null}
          </Surface>

          <Surface
            header={
              <>
                <div>
                  <span className="section-kicker">Append-only evidence</span>
                  <h2>Review audit</h2>
                </div>
                <span className="surface-count">
                  {state.audit_events.length}
                </span>
              </>
            }
          >
            {state.audit_events.length ? (
              <ol className="audit-list">
                {[...state.audit_events].reverse().map((event) => (
                  <li key={`${event.sequence}-${event.invoice_id}`}>
                    <span className="audit-sequence">
                      {event.sequence}
                    </span>
                    <div>
                      <div className="audit-title">
                        <strong>{event.invoice_id}</strong>
                        <span>
                          {humanize(event.previous_status || "new")}
                          <ChevronRight size={13} />
                          {humanize(event.new_status)}
                        </span>
                      </div>
                      <p>{event.note || "No note provided."}</p>
                      <small>
                        {event.reviewer} · {event.reviewer_role} ·{" "}
                        {formatTimestamp(event.timestamp)}
                      </small>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyState
                title="No audit events"
                description="Review decisions will be appended here."
              />
            )}
          </Surface>
        </>
      ) : (
        <EmptyState
          title="No reconciliation runs"
          description="Run the invoice scenario before opening human review."
        />
      )}

      {closeOpen ? (
        <div
          className="dialog-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setCloseOpen(false);
            }
          }}
        >
          <div
            className="dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="close-review-title"
          >
            <button
              type="button"
              className="dialog-close"
              aria-label="Close dialog"
              onClick={() => setCloseOpen(false)}
            >
              <X size={18} />
            </button>
            <span className="feature-icon feature-icon-green">
              <CheckCheck size={21} />
            </span>
            <h2 id="close-review-title">Close this review?</h2>
            <p>
              Closing binds the completed decisions to a content fingerprint
              and prevents further review edits.
            </p>
            {pending ? (
              <div className="warning-banner">
                <CircleAlert size={17} />
                {pending} differences are still pending.
              </div>
            ) : null}
            <label className="field">
              <span>Closure note</span>
              <textarea
                value={closeNote}
                onChange={(event) => setCloseNote(event.target.value)}
                rows={4}
                placeholder="Optional review summary"
              />
            </label>
            <div className="dialog-actions">
              <Button onClick={() => setCloseOpen(false)}>Cancel</Button>
              <Button
                variant="primary"
                disabled={pending > 0 || actionBusy === "close"}
                onClick={() => void closeReview()}
              >
                {actionBusy === "close" ? "Closing…" : "Close review"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
