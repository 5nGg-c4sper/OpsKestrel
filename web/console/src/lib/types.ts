export type RunState = "idle" | "running" | "finished" | "cancelled";

export type ReportStatus =
  | "passed"
  | "failed"
  | "timed_out"
  | "cancelled"
  | "unknown"
  | string;

export type ReviewStatus = "pending" | "confirmed" | "false_positive";

export interface Artifact {
  name: string;
  url: string;
}

export interface Worker {
  worker_id: string;
  hostname: string;
  pid: number;
  state: string;
  current_job_id?: string | null;
  last_heartbeat: string;
  labels: string[];
}

export interface ReportSummary {
  name: string;
  type: string;
  status: ReportStatus;
  duration_seconds: number | null;
  updated_at: number;
  url: string;
}

export interface HistoryEntry {
  kind?: string;
  source_name?: string | null;
  state?: string;
  cancel_requested?: boolean;
  started_at?: string;
  finished_at?: string;
  exit_code?: number | null;
  output_dir?: string;
  run_url: string;
  artifacts: Artifact[];
}

export interface DemoStatus {
  state: RunState;
  exit_code: number | null;
  started_at: number | null;
  elapsed_seconds: number | null;
  output_dir: string | null;
  kind: string | null;
  source_name: string | null;
  log_tail: string[];
  artifacts: Artifact[];
  history: HistoryEntry[];
}

export interface Overview {
  reports: ReportSummary[];
  workers: Worker[];
  worker_error: string | null;
  demo: DemoStatus;
  history: HistoryEntry[];
}

export interface OperatorSession {
  authenticated: boolean;
  operator: string;
  role: "viewer" | "reviewer" | "admin";
}

export interface ReviewSummary {
  pending: number;
  confirmed: number;
  false_positive: number;
}

export interface ReviewRun {
  run: string;
  updated_at: number;
  review_summary?: ReviewSummary;
  closed?: boolean;
  error?: string;
}

export interface ReviewRecord {
  status: ReviewStatus;
  reviewer?: string;
  reviewer_role?: string;
  note?: string;
  updated_at?: string;
}

export interface ReviewResult {
  invoice_id: string;
  status: string;
  review?: ReviewRecord | null;
}

export interface AuditEvent {
  sequence: number;
  timestamp: string;
  invoice_id: string;
  previous_status?: ReviewStatus | null;
  new_status: ReviewStatus;
  reviewer: string;
  reviewer_role: string;
  note?: string;
}

export interface ReviewClosure {
  status: "closed";
  closed_at: string;
  closed_by: string;
  closed_by_role: string;
  note?: string;
}

export interface ReviewState {
  available: boolean;
  run: string;
  review_summary: ReviewSummary;
  closure?: ReviewClosure | null;
  can_close: boolean;
  results: ReviewResult[];
  audit_events: AuditEvent[];
  error?: string;
}

export interface ReviewRunsResponse {
  available: boolean;
  runs: ReviewRun[];
  error?: string;
}

export interface ReconciliationSummary {
  total: number;
  by_status: Record<string, number>;
  all_matched: boolean;
}

export interface ReconciliationResult {
  invoice_id: string;
  status: string;
  expected?: Record<string, unknown>;
  actual?: Record<string, unknown>;
  differences?: string[];
  error?: string | null;
}

export interface ReconciliationPayload {
  expected_csv?: string;
  summary?: ReconciliationSummary;
  reconciliation?: {
    summary: ReconciliationSummary;
    results: ReconciliationResult[];
  };
  results?: ReconciliationResult[];
  collection?: {
    lookups: number;
    errors: number;
    cached: number;
    retried: number;
  };
}
