"""Create reproducible evidence archives for completed SOC Agent runs."""

import hashlib
import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


class EvidenceBundleError(ValueError):
    """Raised when an evidence bundle cannot be created."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_evidence_bundle(run_dir, output_path=None) -> Path:
    root = Path(run_dir).expanduser().resolve()
    if not root.is_dir():
        raise EvidenceBundleError(f"run directory does not exist: {root}")

    target = (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else root / "evidence-bundle.zip"
    )
    target.parent.mkdir(parents=True, exist_ok=True)

    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if path.resolve() == target:
            continue
        if (
            path.name.startswith(f".{target.name}.")
            and path.name.endswith(".tmp")
        ):
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run": root.name,
        "algorithm": "sha256",
        "files": files,
    }

    temporary = tempfile.NamedTemporaryFile(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary_path = Path(temporary.name)
    temporary.close()
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            allowZip64=True,
        ) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
            )
            for item in files:
                archive.write(root / item["path"], item["path"])
        temporary_path.replace(target)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return target
