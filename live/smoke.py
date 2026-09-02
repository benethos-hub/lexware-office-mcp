"""A read-only live check against a real Lexware Office account.

**Run by hand. Never a gate, never in CI, never collected by pytest.** No key
ships with this repository and none goes into a CI secret, so everything
automated has to pass with no key, no network and no account - see SPECS.md
section 14.1. It sits outside `testpaths` for that reason: a filename `pytest`
happens not to match is a convention, a directory it does not walk is not.

What it is for: the offline suite mocks HTTP completely and stays green
through any change in Lexware's field names or response shapes. Only a live
run catches that. This script is the version of that run which anyone holding
an account can repeat, instead of the one-off scripts it replaces.

    uv run python live/smoke.py
    uv run python live/smoke.py --env-file path/to/.env

**It cannot write.** The server it builds is handed a policy with the
`read-only` preset, so a writing tool is not merely unused here, it is absent
from the server and refused if called. That is a structural guarantee rather
than a promise about the code below.

Identifiers are masked in the output, so a report can be pasted somewhere
without carrying real record ids out of the account.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from benethos_lexware_office_mcp.client import ClientProvider  # noqa: E402
from benethos_lexware_office_mcp.config import load_settings  # noqa: E402
from benethos_lexware_office_mcp.policy import ToolPolicy, preset  # noqa: E402
from benethos_lexware_office_mcp.server import build_server  # noqa: E402

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_SEEN: dict[str, str] = {}


def mask(value: Any) -> str:
    """Replace every id with a stable placeholder, so a report can travel."""

    def substitute(match: re.Match[str]) -> str:
        return _SEEN.setdefault(match.group(0), f"<id-{len(_SEEN) + 1}>")

    return _UUID.sub(substitute, str(value))


@dataclass
class Outcome:
    name: str
    state: str  # "ok", "skipped" or "failed"
    detail: str


class Report:
    """What ran, what it found, and whether anything is wrong.

    A check that could not run - because the account holds no record of that
    kind - is reported as **skipped**, never as passed. A live check that
    quietly reports success for work it did not do would be the same hole as
    a test that skips itself.
    """

    def __init__(self) -> None:
        self.outcomes: list[Outcome] = []

    def record(self, name: str, state: str, detail: str = "") -> None:
        self.outcomes.append(Outcome(name, state, detail))
        mark = {"ok": "ok  ", "skipped": "--  ", "failed": "FAIL"}[state]
        print(f"  {mark} {name}{': ' + detail if detail else ''}")

    @property
    def failed(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.state == "failed"]

    def summary(self) -> str:
        counts = {state: 0 for state in ("ok", "skipped", "failed")}
        for outcome in self.outcomes:
            counts[outcome.state] += 1
        return (
            f"{counts['ok']} checked, {counts['skipped']} not applicable, "
            f"{counts['failed']} failed"
        )


async def check(
    report: Report, name: str, body: Callable[[], Awaitable[str | None]]
) -> None:
    """Run one check. A `None` result means the account had nothing to look at."""
    try:
        detail = await body()
    except Exception as exc:  # noqa: BLE001 - a live check reports, it does not raise
        report.record(name, "failed", f"{type(exc).__name__}: {mask(exc)[:160]}")
        return
    if detail is None:
        report.record(name, "skipped", "nothing of this kind in the account")
    else:
        report.record(name, "ok", detail)


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


async def run(env_file: Path | None) -> int:
    settings = load_settings(env_file=env_file)
    if not settings.api_key:
        print(
            "No API key. This script talks to a live account and cannot run "
            "without one.\nSet LXO_MCP_API_KEY, or point --env-file at a file "
            "that does.",
            file=sys.stderr,
        )
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        policy_path = Path(tmp) / "tools.json"
        ToolPolicy(policy_path).save(preset("read-only"))
        settings = replace(settings, tool_policy_path=policy_path)
        provider = ClientProvider(settings)
        server = build_server(settings, provider)
        try:
            return await _checks(server)
        finally:
            await provider.aclose()


async def _checks(server: Any) -> int:
    report = Report()

    async def call(name: str, **arguments: Any) -> Any:
        result = await server.call_tool(name, arguments)
        expect(result.structured_content is not None, f"{name} answered no content")
        return result.structured_content

    tools = [tool.name for tool in await server.list_tools()]
    print(f"\n{len(tools)} read tools offered, no writing tool among them.")
    expect(
        not any(
            name.startswith(("create_", "update_", "delete_", "upload_", "attach_"))
            for name in tools
        ),
        "a writing tool reached a read-only policy",
    )

    # -- who is being read ------------------------------------------------
    profile = await call("get_profile")
    print(
        f"\nAccount: {profile.get('companyName')!r}"
        f"  tax {profile.get('taxType')}"
        f"  small business {profile.get('smallBusiness')}\n"
    )

    async def profile_shape() -> str:
        for field in ("organizationId", "companyName", "taxType"):
            expect(field in profile, f"the profile lost {field}")
        expect("created" not in profile, "the created block is being passed on")
        return f"{len(profile)} fields"

    await check(report, "profile keeps its shape", profile_shape)

    # -- contacts ---------------------------------------------------------
    contacts: dict[str, Any] = {}

    async def contact_page() -> str:
        nonlocal contacts
        contacts = await call("search_contacts", size=5)
        page = contacts["page"]
        for field in ("number", "size", "totalElements", "totalPages", "last"):
            expect(field in page, f"the page envelope lost {field}")
        return f"{page['totalElements']} contacts, page of {page['size']}"

    await check(report, "contact search and the page envelope", contact_page)

    async def contact_record() -> str | None:
        rows = contacts.get("contacts") or []
        if not rows:
            return None
        full = await call("get_contact", contact_id=rows[0]["id"])
        expect("version" in full, "a contact carries no version")
        expect("organizationId" not in full, "organizationId is being passed on")
        return f"{mask(rows[0]['id'])}, version {full['version']}"

    await check(report, "one contact in full", contact_record)

    # -- articles ---------------------------------------------------------
    articles: dict[str, Any] = {}

    async def article_page() -> str:
        nonlocal articles
        articles = await call("search_articles")
        return f"{articles['page']['totalElements']} articles"

    await check(report, "article search", article_page)

    async def article_record() -> str | None:
        rows = articles.get("articles") or []
        if not rows:
            return None
        full = await call("get_article", article_id=rows[0]["id"])
        price = full.get("price") or {}
        expect("leadingPrice" in price, "the price lost its leading side")
        expect(
            "netPrice" in price and "grossPrice" in price,
            "the price no longer carries both figures",
        )
        return f"{full.get('title')!r}, {price['leadingPrice']} leading"

    await check(report, "one article and its price block", article_record)

    # -- vouchers ---------------------------------------------------------
    vouchers: dict[str, Any] = {}

    async def voucher_search() -> str:
        nonlocal vouchers
        vouchers = await call("search_vouchers", size=10)
        return f"{vouchers['page']['totalElements']} documents indexed"

    await check(report, "the voucher list, the only index there is", voucher_search)

    async def bookkeeping_voucher() -> str | None:
        rows = [
            row
            for row in vouchers.get("vouchers") or []
            if row.get("voucherType") in ("salesinvoice", "purchaseinvoice")
        ]
        if not rows:
            return None
        full = await call("get_voucher", voucher_id=rows[0]["id"])
        expect("voucherItems" in full, "a voucher lost its lines")
        expect("version" in full, "a voucher carries no version")
        return f"{full.get('voucherNumber')}, {len(full['voucherItems'])} lines"

    await check(report, "one bookkeeping voucher", bookkeeping_voucher)

    async def payments() -> str | None:
        rows = [
            row
            for row in vouchers.get("vouchers") or []
            if row.get("voucherStatus") in ("open", "paid", "overdue")
        ]
        if not rows:
            return None
        paid = await call("get_payments", voucher_id=rows[0]["id"])
        expect("openAmount" in paid, "payment information lost openAmount")
        return f"open {paid['openAmount']} {paid.get('currency', '')}".strip()

    await check(report, "payment state of a booked document", payments)

    # -- sales documents --------------------------------------------------
    sales_row: dict[str, Any] = {}

    async def sales_document() -> str | None:
        nonlocal sales_row
        rows = [
            row
            for row in vouchers.get("vouchers") or []
            if row.get("voucherType") == "invoice"
        ]
        if not rows:
            return None
        # An issued invoice first, because only that one has been rendered and
        # the download check below reads the same row. Which invoice happens
        # to be newest is not something a live check should depend on.
        issued = [row for row in rows if row.get("voucherStatus") != "draft"]
        sales_row = (issued or rows)[0]
        full = await call(
            "get_sales_document", document_type="invoice", document_id=sales_row["id"]
        )
        for field in ("lineItems", "totalPrice", "taxConditions", "voucherStatus"):
            expect(field in full, f"a sales document lost {field}")
        rendered = "files" in full
        return (
            f"{full.get('voucherNumber')} ({full['voucherStatus']}), "
            f"{'has a rendered document' if rendered else 'nothing to download yet'}"
        )

    await check(report, "one sales document in full", sales_document)

    async def download() -> str | None:
        if not sales_row:
            return None
        full = await call(
            "get_sales_document", document_type="invoice", document_id=sales_row["id"]
        )
        if "files" not in full:
            return None
        saved = await call(
            "download_document", document_type="invoice", document_id=sales_row["id"]
        )
        expect(saved["size"] > 0, "the download is empty")
        expect(
            saved["mimeType"] == "application/pdf",
            "the PDF came back as something else",
        )
        expect(Path(saved["path"]).exists(), "the file is not where the answer says")
        return f"{saved['size']} bytes of {saved['mimeType']}"

    await check(report, "downloading a rendered document", download)

    # -- master data ------------------------------------------------------
    async def master_data() -> str:
        countries = await call("get_master_data", kind="countries", search="Deutsch")
        expect(countries["total"] > 200, "the country list shrank unexpectedly")
        expect(countries["entries"], "no country matched 'Deutsch'")
        categories = await call(
            "get_master_data", kind="posting-categories", search="income", limit=3
        )
        expect(categories["total"] > 100, "the posting categories shrank unexpectedly")
        expect(
            all(row.get("type") == "income" for row in categories["entries"]),
            "the search matched something that is not an income category",
        )
        return f"{countries['total']} countries, {categories['total']} categories"

    await check(report, "master data and its filtering", master_data)

    # -- recurring templates ----------------------------------------------
    async def recurring() -> str:
        page = await call("get_recurring_templates", size=5)
        expect("page" in page, "the recurring templates lost their envelope")
        found = page["page"]["totalElements"]
        if not found:
            return f"{found} templates, so the schedule shape is not checked"
        row = page["templates"][0]
        expect(
            "lineItems" not in row,
            "a list row now carries the lines it never used to",
        )
        full = await call("get_recurring_templates", template_id=row["id"])
        expect("lineItems" in full, "the record lost the lines it will invoice")
        settings = full.get("recurringTemplateSettings") or {}
        for field in ("executionInterval", "nextExecutionDate", "executionStatus"):
            expect(field in settings, f"the schedule lost {field}")
        return (
            f"{found} templates, next run {settings['nextExecutionDate']}, "
            f"{settings['executionInterval'].lower()}, {settings['executionStatus']}, "
            f"{'issues' if settings.get('finalize') else 'drafts'} each run"
        )

    await check(report, "recurring templates", recurring)

    # -- no API call at all -----------------------------------------------
    async def deeplink() -> str | None:
        if not sales_row:
            return None
        link = await call(
            "get_deeplink", target="invoice", target_id=sales_row["id"], action="view"
        )
        expect(link["url"].startswith("http"), "the deeplink is not a URL")
        expect(
            "/permalink/invoices/view/" in link["url"], "the permalink shape changed"
        )
        return mask(link["url"])

    await check(report, "a deeplink, built without a call", deeplink)

    print(f"\n{report.summary()}.")
    if report.failed:
        print("\nWhat failed:", file=sys.stderr)
        for outcome in report.failed:
            print(f"  {outcome.name}: {outcome.detail}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only live check against a Lexware Office account. Run by "
            "hand, never in CI: it needs a real API key and reads real "
            "records. It writes nothing."
        )
    )
    parser.add_argument(
        "--env-file",
        metavar="PATH",
        help="which .env to read instead of looking for one",
    )
    args = parser.parse_args(argv)
    env_file = Path(args.env_file).expanduser() if args.env_file else None
    if env_file is not None and not env_file.is_file():
        print(f"Not a file: {env_file}", file=sys.stderr)
        return 2
    return asyncio.run(run(env_file))


if __name__ == "__main__":
    raise SystemExit(main())
