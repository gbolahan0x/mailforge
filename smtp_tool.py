"""
smtp_tool.py — Simple SMTP Send + Receive Tool
Usage:
  python smtp_tool.py send   --to <addr> --subject <subject> --body <body> [options]
  python smtp_tool.py server [--host 0.0.0.0] [--port 1025]
"""

import argparse
import asyncio
import smtplib
import ssl
import logging
import json
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("smtp_tool")


# ─────────────────────────────────────────────
# SMTP CLIENT
# ─────────────────────────────────────────────

class SMTPClient:
    """Send emails via any SMTP server."""

    def __init__(self, host: str, port: int, username: str = None,
                 password: str = None, use_tls: bool = True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls

    def send(self, from_addr: str, to_addrs: list[str], subject: str,
             body: str, html: str = None) -> bool:
        """
        Send an email. Supports plain text and optional HTML body.
        Returns True on success.
        """
        msg = MIMEMultipart("alternative")
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)
        msg["Subject"] = subject
        msg["Date"] = datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")

        msg.attach(MIMEText(body, "plain"))
        if html:
            msg.attach(MIMEText(html, "html"))

        try:
            if self.use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.host, self.port, context=context) as server:
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.sendmail(from_addr, to_addrs, msg.as_string())
            else:
                with smtplib.SMTP(self.host, self.port) as server:
                    server.ehlo()
                    if self.use_tls:
                        server.starttls()
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.sendmail(from_addr, to_addrs, msg.as_string())

            log.info(f"✅ Email sent to {to_addrs} via {self.host}:{self.port}")
            return True

        except smtplib.SMTPAuthenticationError:
            log.error("❌ Authentication failed. Check your username/password.")
        except smtplib.SMTPConnectError:
            log.error(f"❌ Could not connect to {self.host}:{self.port}")
        except Exception as e:
            log.error(f"❌ Send failed: {e}")

        return False


# ─────────────────────────────────────────────
# SMTP SERVER
# ─────────────────────────────────────────────

try:
    from aiosmtpd.controller import Controller
    from aiosmtpd.handlers import AsyncMessage
    AIOSMTPD_AVAILABLE = True
except ImportError:
    AIOSMTPD_AVAILABLE = False


class InboxHandler:
    """
    Handles incoming SMTP messages.
    Logs each email and saves it as a JSON file in ./inbox/.
    """

    def __init__(self, inbox_dir: str = "inbox"):
        self.inbox_dir = Path(inbox_dir)
        self.inbox_dir.mkdir(exist_ok=True)
        self.received: list[dict] = []

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        envelope.rcpt_tos.append(address)
        return "250 OK"

    async def handle_DATA(self, server, session, envelope):
        timestamp = datetime.now().isoformat()
        mail_from = envelope.mail_from
        rcpt_tos = envelope.rcpt_tos
        content = envelope.content.decode("utf8", errors="replace")

        record = {
            "timestamp": timestamp,
            "from": mail_from,
            "to": rcpt_tos,
            "raw": content,
        }

        self.received.append(record)

        # Save to inbox/
        filename = self.inbox_dir / f"{timestamp.replace(':', '-')}.json"
        filename.write_text(json.dumps(record, indent=2))

        log.info(f"📨 Received email from <{mail_from}> → {rcpt_tos}")
        log.info(f"   Saved to {filename}")

        # Print a preview
        lines = content.splitlines()
        preview_lines = [l for l in lines if l.strip()][:6]
        for line in preview_lines:
            log.info(f"   {line}")

        return "250 Message accepted for delivery"


class SMTPServer:
    """Local SMTP server for receiving and inspecting email."""

    def __init__(self, host: str = "0.0.0.0", port: int = 1025,
                 inbox_dir: str = "inbox"):
        self.host = host
        self.port = port
        self.handler = InboxHandler(inbox_dir)

    def start(self):
        if not AIOSMTPD_AVAILABLE:
            log.error("❌ aiosmtpd is not installed. Run: pip install aiosmtpd")
            return

        controller = Controller(self.handler, hostname=self.host, port=self.port)
        controller.start()

        log.info(f"🚀 SMTP server listening on {self.host}:{self.port}")
        log.info(f"📂 Saving emails to ./inbox/")
        log.info("   Press Ctrl+C to stop.\n")

        try:
            asyncio.get_event_loop().run_forever()
        except KeyboardInterrupt:
            log.info("\n🛑 Server stopped.")
            controller.stop()


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def build_parser():
    parser = argparse.ArgumentParser(
        description="Simple SMTP Tool — send and receive emails",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── send ──
    send_p = sub.add_parser("send", help="Send an email")
    send_p.add_argument("--host",     default="smtp.gmail.com", help="SMTP server host")
    send_p.add_argument("--port",     type=int, default=465,    help="SMTP server port")
    send_p.add_argument("--username", default=os.getenv("SMTP_USER"), help="SMTP username (or set $SMTP_USER)")
    send_p.add_argument("--password", default=os.getenv("SMTP_PASS"), help="SMTP password (or set $SMTP_PASS)")
    send_p.add_argument("--from",     dest="from_addr", required=True, help="Sender address")
    send_p.add_argument("--to",       required=True, nargs="+",        help="Recipient(s)")
    send_p.add_argument("--subject",  required=True,                   help="Email subject")
    send_p.add_argument("--body",     required=True,                   help="Plain text body")
    send_p.add_argument("--html",     default=None,                    help="Optional HTML body")
    send_p.add_argument("--no-tls",   action="store_true",             help="Disable TLS/SSL")

    # ── server ──
    srv_p = sub.add_parser("server", help="Start local SMTP server")
    srv_p.add_argument("--host",  default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    srv_p.add_argument("--port",  type=int, default=1025, help="Bind port (default: 1025)")
    srv_p.add_argument("--inbox", default="inbox", help="Directory to save received emails")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "send":
        client = SMTPClient(
            host=args.host,
            port=args.port,
            username=args.username,
            password=args.password,
            use_tls=not args.no_tls,
        )
        success = client.send(
            from_addr=args.from_addr,
            to_addrs=args.to,
            subject=args.subject,
            body=args.body,
            html=args.html,
        )
        exit(0 if success else 1)

    elif args.command == "server":
        server = SMTPServer(host=args.host, port=args.port, inbox_dir=args.inbox)
        server.start()


if __name__ == "__main__":
    main()
