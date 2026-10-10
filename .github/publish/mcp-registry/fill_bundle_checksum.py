"""Write the Claude Desktop bundle's checksum into server.json.

The registry wants a fileSha256 for the mcpb package, and that hash exists
only once the release has built the bundle. The committed server.json holds
a placeholder of zeros, the release workflow downloads the bundle it just
attached and runs this script before publishing:

    python3 fill_bundle_checksum.py <server.json> <bundle.mcpb>

It refuses a bundle whose file name is not the one the entry points at, and
an entry that no longer holds the placeholder, so a hash is never written
twice or for the wrong file. Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PLACEHOLDER = "0" * 64


def fill(server_json: Path, bundle: Path) -> str:
    entry = json.loads(server_json.read_text(encoding="utf-8"))
    (package,) = [p for p in entry["packages"] if p["registryType"] == "mcpb"]
    named = package["identifier"]
    if named.rsplit("/", 1)[-1] != bundle.name:
        raise SystemExit(f"{bundle.name} is not the file the entry points at: {named}")
    if package["fileSha256"] != PLACEHOLDER:
        raise SystemExit("the entry's fileSha256 is not the placeholder")
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    package["fileSha256"] = digest
    server_json.write_text(
        json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return digest


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: fill_bundle_checksum.py <server.json> <bundle.mcpb>")
    print(fill(Path(sys.argv[1]), Path(sys.argv[2])), file=sys.stderr)
