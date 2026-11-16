from app.pipeline.cleaner import clean_ticket, normalize, strip_signature


def test_signature_stripped():
    body = "printer is offline again\n\nThanks,\nRaj Kumar\nFinance | Chennai-OMR\nPh: 9876543210"
    r = clean_ticket("Printer offline", body)
    assert "Raj Kumar" not in r.text and "Finance |" not in r.text
    assert r.signature_stripped
    assert "printer is offline again" in r.text


def test_disclaimer_stripped():
    body = "cannot login\n\nCONFIDENTIALITY NOTICE: This email and any files transmitted are confidential."
    assert "CONFIDENTIALITY" not in clean_ticket("Login", body).text


def test_mobile_footer_stripped():
    assert "iPhone" not in clean_ticket("Wifi", "wifi is down\n\nSent from my iPhone").text


def test_normalisation_collapses_shouting_and_whitespace():
    assert normalize("URGENT!!!   help   me???") == "URGENT! help me?"


def test_reply_prefix_removed_from_subject():
    assert clean_ticket("RE: FW: VPN down", "body").text.startswith("VPN down")


def test_first_line_always_kept():
    text, _ = strip_signature("Thanks,\nBob")
    assert "Thanks" in text  # never strips the whole message
