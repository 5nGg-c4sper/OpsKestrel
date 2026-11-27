import {
  ArrowRight,
  CircleCheck,
  FileInput,
  FileSpreadsheet,
  Play,
  ShieldCheck,
  UploadCloud
} from "lucide-react";
import {
  useRef,
  useState,
  type DragEvent,
  type FormEvent
} from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useConsole } from "../state/ConsoleProvider";
import { useToast } from "../state/ToastProvider";
import { Button } from "../components/Button";
import { PageHeader } from "../components/PageHeader";
import { Surface } from "../components/Surface";

const acceptedExtensions = [".csv", ".xlsx", ".xlsm", ".pdf"];
const maxUploadBytes = 10 * 1024 * 1024;

export function NewRunPage() {
  const { refresh } = useConsole();
  const { pushToast } = useToast();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState<"demo" | "upload" | null>(null);

  const selectFile = (candidate: File | null) => {
    if (!candidate) {
      setFile(null);
      return;
    }
    const extension = `.${candidate.name.split(".").pop()?.toLowerCase()}`;
    if (!acceptedExtensions.includes(extension)) {
      pushToast("Choose a CSV, XLSX, XLSM, or PDF file.", "error");
      return;
    }
    if (candidate.size > maxUploadBytes) {
      pushToast("The uploaded file must be smaller than 10 MB.", "error");
      return;
    }
    setFile(candidate);
  };

  const startDemo = async () => {
    setBusy("demo");
    try {
      await api.startDemo();
      await refresh();
      pushToast("Invoice reconciliation demo started.", "success");
      navigate("/run");
    } catch (caught) {
      pushToast(
        caught instanceof Error ? caught.message : "Could not start the demo.",
        "error"
      );
    } finally {
      setBusy(null);
    }
  };

  const upload = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) {
      pushToast("Choose an input file first.", "error");
      return;
    }
    setBusy("upload");
    try {
      await api.uploadRun(file);
      await refresh();
      pushToast("Uploaded reconciliation run started.", "success");
      navigate("/run");
    } catch (caught) {
      pushToast(
        caught instanceof Error ? caught.message : "Upload failed.",
        "error"
      );
    } finally {
      setBusy(null);
    }
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    selectFile(event.dataTransfer.files[0] ?? null);
  };

  return (
    <div className="page-stack">
      <PageHeader
        title="New run"
        description="Launch the reference scenario or reconcile your own expected invoice file."
      />

      <div className="new-run-grid">
        <Surface
          className="scenario-surface"
          header={
            <>
              <div>
                <span className="section-kicker">Reference workflow</span>
                <h2>Invoice reconciliation</h2>
              </div>
              <span className="feature-icon feature-icon-blue">
                <FileSpreadsheet size={21} />
              </span>
            </>
          }
          footer={
            <Button
              variant="primary"
              icon={<Play size={16} />}
              disabled={busy !== null}
              onClick={() => void startDemo()}
            >
              {busy === "demo" ? "Starting…" : "Run invoice demo"}
            </Button>
          }
        >
          <p className="lead-copy">
            Open a local enterprise Mock ERP, collect invoice evidence through
            Chrome, apply deterministic reconciliation rules, and publish
            audit-ready reports.
          </p>
          <div className="scenario-facts">
            <div>
              <strong>20</strong>
              <span>synthetic invoices</span>
            </div>
            <div>
              <strong>7</strong>
              <span>result categories</span>
            </div>
            <div>
              <strong>3</strong>
              <span>report formats</span>
            </div>
          </div>
          <ul className="check-list">
            <li>
              <CircleCheck size={16} />
              Deterministic amount, currency, and status comparisons
            </li>
            <li>
              <CircleCheck size={16} />
              Retry, failure screenshots, and checkpoint recovery
            </li>
            <li>
              <CircleCheck size={16} />
              JSON, HTML, XLSX, and evidence bundle outputs
            </li>
          </ul>
        </Surface>

        <Surface
          className="upload-surface"
          header={
            <>
              <div>
                <span className="section-kicker">Operator input</span>
                <h2>Upload expected invoices</h2>
              </div>
              <span className="feature-icon feature-icon-green">
                <FileInput size={21} />
              </span>
            </>
          }
        >
          <form onSubmit={(event) => void upload(event)}>
            <div
              className={`drop-zone ${dragging ? "is-dragging" : ""} ${
                file ? "has-file" : ""
              }`}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
            >
              <input
                ref={inputRef}
                className="sr-only"
                type="file"
                accept={acceptedExtensions.join(",")}
                onChange={(event) =>
                  selectFile(event.target.files?.[0] ?? null)
                }
              />
              <span className="drop-zone-icon">
                {file ? <FileSpreadsheet size={26} /> : <UploadCloud size={28} />}
              </span>
              {file ? (
                <>
                  <strong>{file.name}</strong>
                  <span>{(file.size / 1024).toFixed(1)} KB selected</span>
                </>
              ) : (
                <>
                  <strong>Drop an invoice file here</strong>
                  <span>or choose a local CSV, XLSX, XLSM, or PDF</span>
                </>
              )}
              <Button
                size="compact"
                onClick={() => inputRef.current?.click()}
              >
                {file ? "Choose another file" : "Choose file"}
              </Button>
            </div>

            <div className="upload-constraints">
              <span>Maximum file size: 10 MB</span>
              <span>Input stays on this Mac</span>
            </div>

            <Button
              className="full-width"
              variant="primary"
              type="submit"
              disabled={!file || busy !== null}
              icon={<ArrowRight size={16} />}
            >
              {busy === "upload" ? "Uploading…" : "Upload and run"}
            </Button>
          </form>
        </Surface>
      </div>

      <div className="info-banner">
        <ShieldCheck size={20} />
        <div>
          <strong>Safety boundary</strong>
          <p>
            This demo uses synthetic invoices and a local Mock ERP. Real ERP
            access requires a calibrated adapter and customer-approved
            credentials.
          </p>
        </div>
      </div>
    </div>
  );
}
