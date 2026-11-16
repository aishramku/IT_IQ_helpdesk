import pandas as pd
import pytest

from app.pipeline.cleaner import clean_ticket, redact_pii
from conftest import ROOT


@pytest.mark.parametrize("phone", ["9876543210", "+91 9876543210", "+91-9876543210", "98765 43210"])
def test_phone_numbers_redacted(phone):
    out, counts = redact_pii(f"call me on {phone} please")
    assert phone not in out and "[PHONE]" in out and counts["PHONE"] == 1


def test_employee_id_redacted():
    out, _ = redact_pii("my id is EMP10234 and emp 55555")
    assert "10234" not in out and "[EMP_ID]" in out


def test_email_redacted_in_body():
    out, _ = redact_pii("reach me at john.doe+it@gmail.com or d'souza@acmecorp.com")
    assert "@" not in out and out.count("[EMAIL]") == 2


def test_technical_tokens_survive():
    text = "device LT-OMR-4821 shows 0x800CCC0E and AADSTS50076 on VPN Error 809"
    out, counts = redact_pii(text)
    assert out == text and not counts


def test_redaction_happens_in_clean_ticket_before_storage():
    r = clean_ticket("Help", "my number is 9876543210, mail raj@gmail.com, EMP10234")
    for raw in ("9876543210", "raj@gmail.com", "EMP10234"):
        assert raw not in r.text
    assert set(r.redactions) == {"PHONE", "EMAIL", "EMP_ID"}


def test_no_pii_leaks_anywhere_in_synthetic_dataset():
    csv = ROOT / "data" / "raw" / "tickets.csv"
    if not csv.exists():
        pytest.skip("dataset not generated")
    df = pd.read_csv(csv).head(1500)
    import re
    for s, b in zip(df.subject, df.body):
        text = clean_ticket(s, b).text
        assert not re.search(r"EMP\d{5}", text) and not re.search(r"[\w.]+@[\w.]+\.\w+", text) and not re.search(r"\b9\d{9}\b", text)
