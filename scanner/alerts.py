"""Daily email alert of new A+/A setups.

Builds an HTML digest of the tradeable setups that are *new* since the last
alert and emails it via SMTP. Email is sent only if you configure SMTP via
environment variables — nothing is sent otherwise; a preview HTML is always
written so you can see exactly what would go out.

    python -m scanner.alerts            # new A+/A since last run
    python -m scanner.alerts --all      # all current A+/A (re-send digest)

Environment variables to enable sending:
    GBS_SMTP_HOST, GBS_SMTP_PORT (default 587), GBS_SMTP_USER, GBS_SMTP_PASS
    GBS_ALERT_TO   (recipient)            GBS_ALERT_FROM (default = SMTP_USER)
"""

import argparse
import datetime as dt
import json
import os
import pathlib
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from . import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "journal" / "alerted.json"
PREVIEW = ROOT / "public" / "data" / "alert_preview.html"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _collect(market_key: str, state: dict, send_all: bool) -> tuple[dict, list]:
    data_file = ROOT / "public" / "data" / f"{market_key}.json"
    if not data_file.exists():
        return {}, []
    scan = json.loads(data_file.read_text(encoding="utf-8"))
    tradeable = [r for r in scan["results"] if r["grade"] in config.TRADEABLE_GRADES]
    prev = set(state.get(market_key, []))
    new = [r for r in tradeable if r["symbol"] not in prev]
    state[market_key] = [r["symbol"] for r in tradeable]
    return scan, (tradeable if send_all else new)


def _rows_html(scan: dict, items: list) -> str:
    cur = scan["currency_symbol"]
    out = []
    for r in items:
        warn = f' <span style="color:#c0392b">· LOW R:R ({r["rr_text"]})</span>' if r["low_rr"] else ""
        out.append(f"""<tr>
          <td style="padding:8px 10px;font-weight:700">{r['symbol']}</td>
          <td style="padding:8px 10px;color:#2e7d32;font-weight:700">{r['grade']}</td>
          <td style="padding:8px 10px">{cur}{r['price']:.4f}</td>
          <td style="padding:8px 10px">{r['score']}/{r['score_max']}</td>
          <td style="padding:8px 10px">{r['rr']:.2f}{warn}</td>
          <td style="padding:8px 10px;color:#555">entry {cur}{r['entry']:.4f} · stop {cur}{r['stop']:.4f} · target {cur}{r['target']:.4f}</td>
        </tr>""")
    return "".join(out)


def build_html(digests: list) -> str:
    today = dt.date.today().isoformat()
    blocks = []
    total = 0
    for market_key, scan, items in digests:
        if not items:
            continue
        total += len(items)
        blocks.append(f"""
        <h2 style="font:600 16px/1 Arial;color:#111;margin:24px 0 8px">{scan['label']} — {len(items)} setup(s)</h2>
        <table style="border-collapse:collapse;width:100%;font:13px Arial;color:#222">
          <thead><tr style="background:#f3f4f6;text-align:left;color:#666;font-size:11px;text-transform:uppercase">
            <th style="padding:8px 10px">Ticker</th><th style="padding:8px 10px">Grade</th>
            <th style="padding:8px 10px">Price</th><th style="padding:8px 10px">Score</th>
            <th style="padding:8px 10px">R:R</th><th style="padding:8px 10px">Levels</th>
          </tr></thead><tbody>{_rows_html(scan, items)}</tbody></table>""")
    return f"""<div style="max-width:720px;margin:0 auto;font-family:Arial,sans-serif">
      <h1 style="font:800 20px/1 Arial;color:#111">Googy Boys Scanner — {total} new A+/A setup(s)</h1>
      <p style="color:#666;font-size:13px">{today}</p>
      {''.join(blocks)}
      <p style="color:#999;font-size:11px;margin-top:28px">General information only — not financial advice. Markets carry risk.</p>
    </div>"""


def _send(subject: str, html: str) -> bool:
    host = os.getenv("GBS_SMTP_HOST")
    user = os.getenv("GBS_SMTP_USER")
    pwd = os.getenv("GBS_SMTP_PASS")
    to = os.getenv("GBS_ALERT_TO")
    if not (host and user and pwd and to):
        return False
    port = int(os.getenv("GBS_SMTP_PORT", "587"))
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = os.getenv("GBS_ALERT_FROM", user)
    msg["To"] = to
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, pwd)
        s.sendmail(msg["From"], [to], msg.as_string())
    return True


def run(market_keys: list[str], send_all: bool = False) -> None:
    state = _load_state()
    digests = []
    for mk in market_keys:
        scan, items = _collect(mk, state, send_all)
        if items:
            digests.append((mk, scan, items))
    _save_state(state)

    total = sum(len(i) for _, _, i in digests)
    if not total:
        print("No new A+/A setups to alert.")
        return

    html = build_html(digests)
    PREVIEW.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW.write_text(html, encoding="utf-8")
    subject = f"Googy Boys Scanner — {total} new A+/A setup(s)"

    if _send(subject, html):
        print(f"Sent alert ({total} setups) to {os.getenv('GBS_ALERT_TO')}.")
    else:
        print(f"{total} new setups. SMTP not configured — preview written to {PREVIEW}.")
        print("Set GBS_SMTP_HOST/USER/PASS and GBS_ALERT_TO to enable email.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Email alert of new A+/A setups")
    ap.add_argument("--market", action="append", choices=list(config.MARKETS))
    ap.add_argument("--all", action="store_true", help="include all current A+/A, not just new")
    args = ap.parse_args()
    run(args.market or list(config.MARKETS), send_all=args.all)


if __name__ == "__main__":
    main()
