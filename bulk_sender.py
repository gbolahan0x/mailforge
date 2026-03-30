"""
bulk_sender.py — Bulk Email Sender with CSV, Personalization & Reporting
Usage:
  python bulk_sender.py --csv recipients.csv --subject "Hello {{name}}" --body template.txt
  python bulk_sender.py --csv recipients.csv --subject "Hi {{name}}" --body "Your email is {{email}}"
"""

import argparse
import csv
import json
import logging
import os
import smtplib
import ssl
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from string import Template

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bulk_sender")


# ─────────────────────────────────────────────
# Template Engine
# ─────────────────────────────────────────────

def render_template(text: str, variables: dict) -> str:
    """
    Replace {{key}} placeholders with values from the variables dict.
    Example: "Hello {{name}}" + {"name": "Ada"} → "Hello Ada"
    """
    for key, value in variables.items():
        text = text.replace(f"{{{{{key}}}}}", str(value))
    return text


# ─────────────────────────────────────────────
# CSV Loader
# ─────────────────────────────────────────────

def load_recipients(csv_path: str) -> list[dict]:
    """
    Load recipients from a CSV file.
    Required column: email
    Optional columns: name, and any custom fields used in templates.
    """
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
# Bulk Sender
# ─────────────────────────────────────────────

class BulkSender:
    def __init__(self, host: str, port: int, username: str = None,
                 password: str = None, use_tls: bool = True,
                 delay: float = 1.5):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.delay = delay  # seconds between emails (avoid spam flags)

    def _connect(self):
        if self.use_tls:
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(self.host, self.port, context=context)
        else:
            server = smtplib.SMTP(self.host, self.port)
            server.ehlo()

        if self.username and self.password:
            server.login(self.username, self.password)

        return server

    def send_bulk(self, from_addr: str, recipients: list[dict],
                  subject_template: str, body_template: str,
                  html_template: str = None) -> dict:
        """
        Send personalized emails to all recipients.
        Returns a report dict with success/fail counts and details.
        """
        report = {
            "total": len(recipients),
            "sent": 0,
            "failed": 0,
            "results": [],
            "started_at": datetime.now().isoformat(),
        }

        log.info(f"🚀 Starting bulk send to {len(recipients)} recipients...")
        log.info(f"   SMTP: {self.host}:{self.port}")
        log.info(f"   Delay: {self.delay}s between emails\n")

        try:
            server = self._connect()
        except Exception as e:
            log.error(f"❌ Could not connect to SMTP server: {e}")
            report["error"] = str(e)
            return report

        for i, recipient in enumerate(recipients, 1):
            email = recipient.get("email")
            name = recipient.get("name", email)

            # Render personalized content
            variables = {**recipient, "name": name, "email": email}
            subject = render_template(subject_template, variables)
            body = render_template(body_template, variables)
            html = render_template(html_template, variables) if html_template else None

            # Build message
            msg = MIMEMultipart("alternative")
            msg["From"] = from_addr
            msg["To"] = email
            msg["Subject"] = subject
            msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")
            msg.attach(MIMEText(body, "plain"))
            if html:
                msg.attach(MIMEText(html, "html"))

            # Send
            try:
                server.sendmail(from_addr, [email], msg.as_string())
                log.info(f"  [{i}/{report['total']}] ✅ Sent to {name} <{email}>")
                report["sent"] += 1
                report["results"].append({"email": email, "name": name, "status": "sent"})
            except Exception as e:
                log.warning(f"  [{i}/{report['total']}] ❌ Failed for {email}: {e}")
                report["failed"] += 1
                report["results"].append({"email": email, "name": name, "status": "failed", "error": str(e)})

            # Rate limiting — pause between sends
            if i < len(recipients):
                time.sleep(self.delay)

        try:
            server.quit()
        except Exception:
            pass

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
    print(f"  Total:   {report['total']}")
    print(f"  ✅ Sent:  {report['sent']}")
    print(f"  ❌ Failed: {report['failed']}")
    if report.get("finished_at") and report.get("started_at"):
        start = datetime.fromisoformat(report["started_at"])
        end = datetime.fromisoformat(report["finished_at"])
        duration = (end - start).seconds
        print(f"  ⏱  Duration: {duration}s")
    print("─" * 40 + "\n")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        description="Bulk Email Sender — CSV + Personalization + Reporting",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--csv",      required=True,  help="Path to recipients CSV file")
    parser.add_argument("--from",     dest="from_addr", required=True, help="Sender email address")
    parser.add_argument("--subject",  required=True,  help="Subject line. Use {{name}}, {{email}}, etc.")
    parser.add_argument("--body",     required=True,  help="Plain text body or path to a .txt template file")
    parser.add_argument("--html",     default=None,   help="HTML body or path to a .html template file")
    parser.add_argument("--host",     default="smtp.gmail.com", help="SMTP host (default: smtp.gmail.com)")
    parser.add_argument("--port",     type=int, default=465,    help="SMTP port (default: 465)")
    parser.add_argument("--username", default=os.getenv("SMTP_USER"), help="SMTP username or set $SMTP_USER")
    parser.add_argument("--password", default=os.getenv("SMTP_PASS"), help="SMTP password or set $SMTP_PASS")
    parser.add_argument("--no-tls",   action="store_true", help="Disable TLS")
    parser.add_argument("--delay",    type=float, default=1.5,  help="Seconds between emails (default: 1.5)")
    parser.add_argument("--reports",  default="reports", help="Directory to save reports (default: reports/)")
    return parser


def resolve_body(value: str) -> str:
    """If value is a file path, read it. Otherwise use it as-is."""
    path = Path(value)
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")
    return value


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Load recipients
    try:
        recipients = load_recipients(args.csv)
    except (FileNotFoundError, ValueError) as e:
        log.error(f"❌ {e}")
        exit(1)

    if not recipients:
        log.error("❌ No valid recipients found in CSV.")
        exit(1)

    # Resolve body/html (file or inline string)
    body_template = resolve_body(args.body)
    html_template = resolve_body(args.html) if args.html else None

    # Send
    sender = BulkSender(
        host=args.host,
        port=args.port,
        username=args.username,
        password=args.password,
        use_tls=not args.no_tls,
        delay=args.delay,
    )

    report = sender.send_bulk(
        from_addr=args.from_addr,
        recipients=recipients,
        subject_template=args.subject,
        body_template=body_template,
        html_template=html_template,
    )

    # Save and print report
    report_path = save_report(report, args.reports)
    print_summary(report)
    log.info(f"📄 Full report saved to {report_path}")


if __name__ == "__main__":
    main()
