"""Generate SHA-256 checksums for the specified release assets."""
import hashlib
import sys
from pathlib import Path

paths = sorted(Path(value).resolve(strict=True) for value in sys.argv[1:])
if not paths or len({path.parent for path in paths}) != 1:
    raise SystemExit("Pass at least one asset in the same output folder")
lines = []
for path in paths:
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    lines.append(f"{digest}  {path.name}")
manifest = "\n".join(lines) + "\n"
(paths[0].parent / "SHA256SUMS.txt").write_text(manifest, encoding="utf-8")
print(manifest, end="")
