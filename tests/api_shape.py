"""Record the shape of every read endpoint, so drift can be seen later.

**Run by hand. Never a gate, never in CI, never collected by pytest.** Named
without a ``test_`` prefix for the same reason as ``smoke.py``, see SPECS.md
section 14.1.

    uv run python tests/api_shape.py
    uv run python tests/api_shape.py --env-file path/to/.env

``smoke.py`` asks whether the calls this server makes still work. This asks a
different question: whether the answers still look the same. The two are not
the same check. Everything null or empty is dropped on the way to the client,
so a field that disappeared upstream looks identical downstream, and a field
that appeared is invisible by construction. Both are read here, before any of
that happens.

Each run writes one timestamped file into ``tests/api-shapes/``. Comparing two
of them is an ordinary ``diff``, which is the whole point: the alternative is
reading dated prose in SPECS.md section 5 and hoping to notice.

**What a file may contain, and what it may not.** Field names, their JSON
types, and - for a short list of fields whose *vocabulary* is the thing that
drifts - the values seen. Nothing else. No id, no name, no address, no amount,
no date. That rule is what makes these files safe to version, and
``VOCABULARY`` below is the entire exception to it: every entry is a closed
set defined by the API, never something a person typed.

Read-only by construction: :func:`_get` is the only request helper and it
sends ``GET``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from benethos_lexware_office_mcp.client import LexwareClient  # noqa: E402
from benethos_lexware_office_mcp.config import load_settings  # noqa: E402

HERE = Path(__file__).resolve().parent
SHAPES = HERE / "api-shapes"

# Fields whose set of allowed values is worth recording, because a changed
# vocabulary is drift that a type alone cannot show - which is how
# `voucherStatus: unchecked` stopped being accepted between two Thursdays,
# see SPECS.md section 5.
#
# Every entry here is a closed set the API defines. Free text a person typed
# is deliberately absent: `unitName`, `title`, `note` and `remark` are all
# vocabulary-shaped and none of them belongs in a versioned file.
VOCABULARY = frozenset(
    {
        "articleType",
        "electronicDocumentProfile",
        "executionInterval",
        "language",
        "leadingPrice",
        "paymentItemType",
        "paymentStatus",
        "shippingType",
        "taxClassification",
        "taxType",
        "type",
        "voucherStatus",
        "voucherType",
    }
)

# How many entries of a list to look into. Enough that an optional field on a
# later row is still seen, few enough that the file stays a shape rather than
# a copy of the account.
SAMPLE = 5


def describe(
    node: Any, path: str = "", out: dict[str, set[str]] | None = None
) -> dict[str, set[str]]:
    """One response, reduced to ``field path -> the types seen there``."""
    if out is None:
        out = {}
    if isinstance(node, dict):
        for key in sorted(node):
            describe(node[key], f"{path}.{key}" if path else key, out)
    elif isinstance(node, list):
        out.setdefault(f"{path}[]", set()).add("array")
        for item in node[:SAMPLE]:
            describe(item, f"{path}[]", out)
    else:
        leaf = path.rsplit(".", 1)[-1].removesuffix("[]")
        kind = type(node).__name__
        if leaf in VOCABULARY and isinstance(node, str):
            out.setdefault(path, set()).add(f"{kind}={node}")
        else:
            out.setdefault(path, set()).add(kind)
    return out


class Capture:
    """What was read, and what could not be."""

    def __init__(self) -> None:
        self.shapes: dict[str, dict[str, set[str]]] = {}
        self.skipped: list[str] = []

    def add(self, endpoint: str, payload: Any) -> None:
        self.shapes[endpoint] = describe(payload)
        print(f"  ok   {endpoint}", flush=True)

    def skip(self, endpoint: str, why: str) -> None:
        self.skipped.append(f"{endpoint} - {why}")
        print(f"  --   {endpoint}: {why}", flush=True)

    def render(self, taken: datetime) -> str:
        lines = [
            "# API response shapes",
            "",
            f"Taken {taken.strftime('%Y-%m-%d %H:%M UTC')} "
            f"by tests/api_shape.py against a live account.",
            "",
            "Field names and JSON types. Values appear only for the closed "
            "vocabularies the script names,",
            "never for anything a person entered. See the module docstring "
            "for the rule.",
            "",
            f"{len(self.shapes)} endpoints read"
            + (f", {len(self.skipped)} not available" if self.skipped else ""),
        ]
        for note in self.skipped:
            lines.append(f"  not available: {note}")
        for endpoint in sorted(self.shapes):
            lines.append("")
            lines.append(f"## {endpoint}")
            for field in sorted(self.shapes[endpoint]):
                lines.append(
                    f"{field}: {'|'.join(sorted(self.shapes[endpoint][field]))}"
                )
        return "\n".join(lines) + "\n"


DOCUMENT_PATHS = {
    "invoice": "invoices",
    "quotation": "quotations",
    "creditnote": "credit-notes",
    "orderconfirmation": "order-confirmations",
    "deliverynote": "delivery-notes",
    "downpaymentinvoice": "down-payment-invoices",
}

MASTER_DATA = ("countries", "payment-conditions", "posting-categories", "print-layouts")

# A bookkeeping voucher, as opposed to a sales document. The two live at
# different paths and only the second has a rendered file, see SPECS.md
# section 5.
BOOKKEEPING = {
    "salesinvoice",
    "purchaseinvoice",
    "salescreditnote",
    "purchasecreditnote",
}


async def collect(client: LexwareClient, capture: Capture) -> None:
    async def _get(path: str, **params: Any) -> Any:
        response = await client.request("GET", path, params=params or None)
        return response.json()

    capture.add("GET /v1/profile", await _get("/v1/profile"))

    contacts = await _get("/v1/contacts", page=0, size=25)
    capture.add("GET /v1/contacts", contacts)
    rows = contacts.get("content") or []
    # A person and a company carry different blocks, and reading only the
    # first row would report whichever the account happens to start with.
    for wanted in ("company", "person"):
        row = next((r for r in rows if wanted in r), None)
        if row is None:
            capture.skip(f"GET /v1/contacts/{{id}} ({wanted})", f"no {wanted} contact")
            continue
        capture.add(
            f"GET /v1/contacts/{{id}} ({wanted})",
            await _get(f"/v1/contacts/{row['id']}"),
        )

    # 25 is the smallest page this endpoint accepts, alone among the lists.
    articles = await _get("/v1/articles", page=0, size=25)
    capture.add("GET /v1/articles", articles)
    arows = articles.get("content") or []
    if arows:
        capture.add(
            "GET /v1/articles/{id}", await _get(f"/v1/articles/{arows[0]['id']}")
        )
    else:
        capture.skip("GET /v1/articles/{id}", "no article in the account")

    listing = await _get(
        "/v1/voucherlist", page=0, size=100, voucherType="any", voucherStatus="any"
    )
    capture.add("GET /v1/voucherlist", listing)
    vrows = listing.get("content") or []

    voucher = next((r for r in vrows if r.get("voucherType") in BOOKKEEPING), None)
    if voucher is None:
        capture.skip("GET /v1/vouchers/{id}", "no bookkeeping voucher")
        capture.skip("GET /v1/payments/{id}", "no bookkeeping voucher")
    else:
        capture.add(
            "GET /v1/vouchers/{id}", await _get(f"/v1/vouchers/{voucher['id']}")
        )
        capture.add(
            "GET /v1/payments/{id}", await _get(f"/v1/payments/{voucher['id']}")
        )

    for voucher_type, resource in DOCUMENT_PATHS.items():
        row = next((r for r in vrows if r.get("voucherType") == voucher_type), None)
        if row is None:
            capture.skip(
                f"GET /v1/{resource}/{{id}}", f"no {voucher_type} in the account"
            )
            continue
        capture.add(
            f"GET /v1/{resource}/{{id}}", await _get(f"/v1/{resource}/{row['id']}")
        )

    capture.add(
        "GET /v1/recurring-templates",
        await _get("/v1/recurring-templates", page=0, size=25),
    )

    for kind in MASTER_DATA:
        capture.add(f"GET /v1/{kind}", await _get(f"/v1/{kind}"))


async def run(env_file: Path | None) -> int:
    settings = load_settings(env_file=env_file)
    if not settings.api_key:
        print(
            "No API key. This script reads a live account and cannot run "
            "without one.\nSet LXO_MCP_API_KEY, or point --env-file at a file "
            "that does.",
            file=sys.stderr,
        )
        return 2

    capture = Capture()
    taken = datetime.now(UTC)
    print("reading, this makes about twenty requests\n")
    async with LexwareClient(settings) as client:
        await collect(client, capture)

    SHAPES.mkdir(parents=True, exist_ok=True)
    target = SHAPES / f"shape-{taken.strftime('%Y%m%dT%H%MZ')}.txt"
    target.write_text(capture.render(taken), encoding="utf-8")

    print(f"\n{len(capture.shapes)} endpoints written to {target.name}")
    previous = sorted(p for p in SHAPES.glob("shape-*.txt") if p != target)
    if previous:
        print(f"compare with:  git diff --no-index {previous[-1].name} {target.name}")
    else:
        print("first capture, so nothing to compare it with yet")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=None, metavar="PATH")
    args = parser.parse_args(argv)
    return asyncio.run(run(args.env_file))


if __name__ == "__main__":
    raise SystemExit(main())
