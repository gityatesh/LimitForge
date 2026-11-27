"""Unit tests for the bank-statement CSV parser (feature 10). No database needed."""
import pytest

from app.services.statement_parser import StatementError, parse_statement

GOOD = b"""date,description,credit,debit
2026-08-01,Salary,90000,
2026-08-05,Rent,,30000
01/09/2026,Salary,90000,
05/09/2026,Rent,,30000
10/09/2026,Bonus,"1,20,000",
"""


def test_good_statement_is_averaged_per_month():
    s = parse_statement(GOOD)
    assert s.transaction_count == 5 and s.months_covered == 2
    assert s.avg_monthly_income == (90000 + 90000 + 120000) / 2     # 150000
    assert s.avg_monthly_expenses == 30000


@pytest.mark.parametrize("content,message", [
    (b"date,amount\n2026-01-01,5", "Missing column"),
    (b"date,description,credit,debit\n2026-08-01,Salary,90000,\n2026-08-05,Rent,,1", "at least 2"),
    (b"date,description,credit,debit\n31-12-2026,Salary,90000,\n", "must be YYYY-MM-DD"),
    (b"date,description,credit,debit\n2026-08-01,Salary,abc,\n2026-09-01,x,1,\n", "not a number"),
    (b"date,description,credit,debit\n2026-08-01,Odd,100,50\n2026-09-01,x,1,\n", "not both"),
    (b"date,description,credit,debit\n2026-08-01,Neg,-100,\n2026-09-01,x,1,\n", "negative"),
    (b"date,description,credit,debit\n", "no transactions"),
    (b"\xff\xfe\x00bad", "UTF-8"),
])
def test_bad_statements_rejected_with_clear_message(content, message):
    with pytest.raises(StatementError, match=message):
        parse_statement(content)


def test_excel_bom_is_accepted():
    assert parse_statement(b"\xef\xbb\xbf" + GOOD).months_covered == 2