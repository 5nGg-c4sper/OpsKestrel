import { className, humanize } from "../lib/format";

interface StatusBadgeProps {
  status: string;
  subtle?: boolean;
}

export function StatusBadge({ status, subtle = false }: StatusBadgeProps) {
  const normalized = status.toLowerCase().replaceAll(" ", "_");
  return (
    <span
      className={className(
        "status-badge",
        `status-${normalized}`,
        subtle && "status-subtle"
      )}
    >
      <span className="status-dot" aria-hidden="true" />
      {humanize(status)}
    </span>
  );
}
