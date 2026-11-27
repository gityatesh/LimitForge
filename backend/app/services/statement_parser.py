"""Bank-statement CSV -> average monthly income and expenses (feature 10).

Expected CSV (header row required, any column order):
    date,description,credit,debit
    2026-08-01,Salary ACME Ltd,100000,
    2026-08-03,Rent,,25000
Dates: YYYY-MM-DD or DD/MM/YYYY.  Money: plain numbers, commas allowed ("1,00,000").

Honest limit: this reads what the customer uploads. It does NOT prove the file came from a
bank (real systems use Account Aggregator / bank APIs). We therefore record the source as
STATEMENT, so staff can see where the numbers came from.
"""
import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

MAX_BYTES = 1_000_000          # 1 MB
MAX_ROWS = 5_000
MIN_MONTHS = 2                 # one month is too little to average
REQUIRED_COLUMNS = {"date", "description", "credit", "debit"}


class StatementError(ValueError):
    """Raised with a human-readable message; the router turns it into a 422."""


@dataclass
class StatementSummary:
    transaction_count: int
    months_covered: int
    avg_monthly_income: float
    avg_monthly_expenses: float


def _parse_date(raw: str, line: int) -> date:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise StatementError(f"Line {line}: date '{raw}' must be YYYY-MM-DD or DD/MM/YYYY.")


def _parse_money(raw: str | None, line: int) -> float:
    raw = (raw or "").strip().replace(",", "")
    if raw == "":
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        raise StatementError(f"Line {line}: amount '{raw}' is not a number.")
    if value < 0:
        raise StatementError(f"Line {line}: use the credit/debit columns instead of negative amounts.")
    return value


def parse_statement(content: bytes) -> StatementSummary:
    if len(content) > MAX_BYTES:
        raise StatementError("File is larger than 1 MB.")
    try:
        text = content.decode("utf-8-sig")       # -sig strips the BOM Excel adds
    except UnicodeDecodeError:
        raise StatementError("File must be a UTF-8 CSV.")

    reader = csv.DictReader(io.StringIO(text))
    headers = {h.strip().lower() for h in (reader.fieldnames or [])}
    missing = REQUIRED_COLUMNS - headers
    if missing:
        raise StatementError(f"Missing column(s): {', '.join(sorted(missing))}. "
                             "Expected: date, description, credit, debit.")

    credits: dict[tuple[int, int], float] = {}
    debits: dict[tuple[int, int], float] = {}
    count = 0
    for line, row in enumerate(reader, start=2):          # line 1 is the header
        row = {k.strip().lower(): v for k, v in row.items() if k}
        if not any((v or "").strip() for v in row.values()):
            continue                                       # skip blank lines
        count += 1
        if count > MAX_ROWS:
            raise StatementError(f"Too many rows (max {MAX_ROWS}).")
        d = _parse_date(row["date"], line)
        credit, debit = _parse_money(row["credit"], line), _parse_money(row["debit"], line)
        if credit and debit:
            raise StatementError(f"Line {line}: a row can be a credit or a debit, not both.")
        month = (d.year, d.month)
        credits[month] = credits.get(month, 0.0) + credit
        debits[month] = debits.get(month, 0.0) + debit

    months = set(credits) | set(debits)
    if count == 0:
        raise StatementError("The file has no transactions.")
    if len(months) < MIN_MONTHS:
        raise StatementError(f"Statement must cover at least {MIN_MONTHS} different months.")

    n = len(months)
    return StatementSummary(
        transaction_count=count,
        months_covered=n,
        avg_monthly_income=round(sum(credits.values()) / n, 2),
        avg_monthly_expenses=round(sum(debits.values()) / n, 2),
    )