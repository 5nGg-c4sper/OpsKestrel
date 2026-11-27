import { Download, ExternalLink } from "lucide-react";
import type { Artifact } from "../lib/types";

interface ArtifactLinksProps {
  artifacts: Artifact[];
  compact?: boolean;
}

export function ArtifactLinks({
  artifacts,
  compact = false
}: ArtifactLinksProps) {
  if (!artifacts.length) {
    return <span className="muted">No artifacts yet</span>;
  }
  return (
    <div className={compact ? "artifact-list compact" : "artifact-list"}>
      {artifacts.map((artifact) => (
        <a
          className="artifact-link"
          href={artifact.url}
          key={artifact.name}
          target="_blank"
          rel="noreferrer"
        >
          {artifact.name.endsWith(".zip") ? (
            <Download size={15} />
          ) : (
            <ExternalLink size={15} />
          )}
          <span>{artifact.name}</span>
        </a>
      ))}
    </div>
  );
}
