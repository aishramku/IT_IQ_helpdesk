import pandas as pd

from app.intelligence.recurring import analyze


def _frame():
    rows = []
    days = pd.date_range("2026-08-17", periods=70, freq="D")  # 10 full weeks starting Monday
    for d in days:
        if d.dayofweek < 5:
            rows.append(dict(created_at=d + pd.Timedelta(hours=14), category="Email"))  # steady background
        if d.dayofweek == 0:
            rows += [dict(created_at=d + pd.Timedelta(hours=9, minutes=m), category="Network", text="vpn will not connect") for m in range(0, 50, 10)]
    df = pd.DataFrame(rows)
    df["clean_text"] = df.get("text", pd.Series(["issue"] * len(df))).fillna("issue")
    df["dow"], df["hour"], df["date"] = df.created_at.dt.dayofweek, df.created_at.dt.hour, df.created_at.dt.normalize()
    for c, v in dict(is_malicious=False, duplicate_of=None, location="Chennai-OMR", kb_article_id=None, ticket_type="Incident",
                     requester_email="a@x.com", initial_team=None, assigned_team=None, resolution_hours=1.0, priority="P3").items():
        df[c] = v
    return df


def test_monday_vpn_spike_detected_with_plain_english_advice():
    out = [i for i in analyze(_frame()) if i.title.startswith("VPN spike")]
    assert out and "Monday" in out[0].title and "09:00" in out[0].title
    assert "licence" in out[0].recommendation
