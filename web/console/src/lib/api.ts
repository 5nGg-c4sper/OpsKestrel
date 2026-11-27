import type {
  DemoStatus,
  OperatorSession,
  Overview,
  ReconciliationPayload,
  ReviewRunsResponse,
  ReviewState,
  ReviewStatus
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function parseResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();
  if (!response.ok) {
    const message =
      typeof payload === "object" && payload && "error" in payload
        ? String(payload.error)
        : `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status);
  }
  return payload as T;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  token?: string
): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(path, {
    ...init,
    headers
  });
  return parseResponse<T>(response);
}

function jsonRequest<T>(
  path: string,
  payload: unknown,
  token?: string
): Promise<T> {
  return request<T>(
    path,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    },
    token
  );
}

export const api = {
  overview: () => request<Overview>("/api/overview"),
  demoStatus: () => request<DemoStatus>("/api/demo/status"),
  startDemo: () =>
    request<{ started: boolean; output_dir?: string; error?: string }>(
      "/api/demo/run",
      { method: "POST" }
    ),
  cancelRun: () =>
    request<{ cancelled: boolean; error?: string }>("/api/demo/cancel", {
      method: "POST"
    }),
  createBundle: () =>
    request<{ created: boolean; name?: string; url?: string; error?: string }>(
      "/api/demo/bundle",
      { method: "POST" }
    ),
  uploadRun: (file: File) =>
    request<{ started: boolean; output_dir?: string; error?: string }>(
      `/api/upload/run?filename=${encodeURIComponent(file.name)}`,
      { method: "POST", body: file }
    ),
  operatorSession: (token: string) =>
    request<OperatorSession>("/api/session", {}, token),
  reviewRuns: (token: string) =>
    request<ReviewRunsResponse>("/api/review/runs", {}, token),
  reviewState: (token: string, run: string) =>
    request<ReviewState>(
      `/api/review/state?run=${encodeURIComponent(run)}`,
      {},
      token
    ),
  saveReview: (
    token: string,
    payload: {
      run: string;
      invoice_id: string;
      status: ReviewStatus;
      note: string;
    }
  ) => jsonRequest<ReviewState>("/api/review", payload, token),
  saveReviews: (
    token: string,
    payload: {
      run: string;
      invoice_ids: string[];
      status: ReviewStatus;
      note: string;
    }
  ) => jsonRequest<ReviewState>("/api/review/batch", payload, token),
  closeReview: (token: string, run: string, note: string) =>
    jsonRequest<ReviewState>("/api/review/close", { run, note }, token),
  reconciliation: (url: string) =>
    request<ReconciliationPayload>(url)
};
