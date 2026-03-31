"""
bulk_sender.py — Bulk Email Sender via Brevo API
"""

import argparse
import csv
import json
import logging
import os
import time
import requests
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bulk_sender")

BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


# ─────────────────────────────────────────────
# Template Engine
# ─────────────────────────────────────────────

def render_template(text: str, variables: dict) -> str:
    for key, value in variables.items():
        text = text.replace(f"{{{{{key}}}}}", str(value))
    return text


# ─────────────────────────────────────────────
# CSV Loader
# ─────────────────────────────────────────────

def load_recipients(csv_path: str) -> list[dict]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    recipients = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "email" not in (reader.fieldnames or []):
            raise ValueError("CSV must have an 'email' column")
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            if row.get("email"):
                recipients.append(row)

    log.info(f"📋 Loaded {len(recipients)} recipients from {csv_path}")
    return recipients


# ─────────────────────────────────────────────
# Bulk Sender — Brevo API
# ─────────────────────────────────────────────

class BulkSender:
    def __init__(self, api_key: str = None, delay: float = 0.5,
                 host: str = None, port: int = None,
                 username: str = None, password: str = None,
                 use_tls: bool = True):
        self.api_key = api_key or os.getenv("BREVO_API_KEY", "")
        self.delay = delay

    def _send_one(self, from_addr: str, from_name: str,
                  to_email: str, to_name: str,
                  subject: str, body: str, html: str = None) -> dict:
        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json",
        }
        payload = {
            "sender": {"name": from_name, "email": from_addr},
            "to": [{"email": to_email, "name": to_name}],
            "subject": subject,
            "textContent": body,
        }
        if html:
            payload["htmlContent"] = html

        response = requests.post(BREVO_API_URL, json=payload, headers=headers, timeout=15)
        return response

    def send_bulk(self, from_addr: str, recipients: list[dict],
                  subject_template: str, body_template: str,
                  html_template: str = None) -> dict:

        if not self.api_key:
            return {
                "total": len(recipients), "sent": 0,
                "failed": len(recipients),
                "error": "BREVO_API_KEY not set",
                "results": [],
                "started_at": datetime.now().isoformat(),
                "finished_at": datetime.now().isoformat(),
            }

        from_name = from_addr.split("@")[0].title()

        report = {
            "total": len(recipients),
            "sent": 0, "failed": 0,
            "results": [],
            "started_at": datetime.now().isoformat(),
        }

        log.info(f"🚀 Starting bulk send to {len(recipients)} recipients via Brevo...")

        for i, recipient in enumerate(recipients, 1):
            email = recipient.get("email")
            name  = recipient.get("name", email)

            variables = {**recipient, "name": name, "email": email}
            subject   = render_template(subject_template, variables)
            body      = render_template(body_template, variables)
            html      = render_template(html_template, variables) if html_template else None

            try:
                response = self._send_one(
                    from_addr=from_addr, from_name=from_name,
                    to_email=email, to_name=name,
                    subject=subject, body=body, html=html
                )

                if response.status_code in (200, 201):
                    log.info(f"  [{i}/{report['total']}] ✅ Sent to {name} <{email}>")
                    report["sent"] += 1
                    report["results"].append({
                        "email": email, "name": name, "status": "sent"
                    })
                else:
                    error = response.json().get("message", response.text)
                    log.warning(f"  [{i}/{report['total']}] ❌ Failed for {email}: {error}")
                    report["failed"] += 1
                    report["results"].append({
                        "email": email, "name": name,
                        "status": "failed", "error": error
                    })

            except Exception as e:
                log.warning(f"  [{i}/{report['total']}] ❌ Error for {email}: {e}")
                report["failed"] += 1
                report["results"].append({
                    "email": email, "name": name,
                    "status": "failed", "error": str(e)
                })

            if i < len(recipients):
                time.sleep(self.delay)

        report["finished_at"] = datetime.now().isoformat()
        return report


# ─────────────────────────────────────────────
# Report Saver
# ─────────────────────────────────────────────

def save_report(report: dict, output_dir: str = "reports"):
    Path(output_dir).mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = Path(output_dir) / f"report_{timestamp}.json"
    path.write_text(json.dumps(report, indent=2))
    return path


def print_summary(report: dict):
    print("\n" + "─" * 40)
    print("📊 BULK SEND REPORT")
    print("─" * 40)
    print(f"  Total:    {report['total']}")
    print(f"  ✅ Sent:   {report['sent']}")
    print(f"  ❌ Failed: {report['failed']}")
    print("─" * 40 + "\n")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(description="Bulk Email Sender via Brevo API")
    parser.add_argument("--csv",     required=True)
    parser.add_argument("--from",    dest="from_addr", required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--body",    required=True)
    parser.add_argument("--html",    default=None)
    parser.add_argument("--api-key", default=os.getenv("BREVO_API_KEY"))
    parser.add_argument("--delay",   type=float, default=0.5)
    parser.add_argument("--reports", default="reports")
    return parser


def resolve_body(value: str) -> str:
    path = Path(value)
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")
    return value


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        recipients = load_recipients(args.csv)
    except (FileNotFoundError, ValueError) as e:
        print(f"❌ {e}")
        exit(1)

    body_template = resolve_body(args.body)
    html_template = resolve_body(args.html) if args.html else None

    sender = BulkSender(api_key=args.api_key, delay=args.delay)
    report = sender.send_bulk(
        from_addr=args.from_addr,
        recipients=recipients,
        subject_template=args.subject,
        body_template=body_template,
        html_template=html_template,
    )

    save_report(report, args.reports)
    print_summary(report)


if __name__ == "__main__":
    main()
