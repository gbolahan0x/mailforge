"""
app.py — MailForge Web UI (Brevo API)
Run: python app.py
"""

import csv
import io
import json
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from bulk_sender import BulkSender, save_report
from smtp_tool import SMTPServer
from aiosmtpd.controller import Controller

app = Flask(__name__)

INBOX_DIR = Path("inbox")
REPORTS_DIR = Path("reports")
INBOX_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

_smtp_server = None
_smtp_controller = None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/send", methods=["POST"])
def api_send():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid JSON body"}), 400

        api_key        = data.get("api_key") or os.getenv("BREVO_API_KEY", "")
        from_addr      = data.get("from_addr", "")
        subject        = data.get("subject", "")
        body           = data.get("body", "")
        delay          = float(data.get("delay") or 0.5)
        recipients_raw = data.get("recipients", [])

        if not recipients_raw:
            return jsonify({"error": "No recipients provided"}), 400
        if not from_addr or not subject or not body:
            return jsonify({"error": "from_addr, subject, and body are required"}), 400
        if not api_key:
            return jsonify({"error": "Brevo API key missing. Add it in Settings."}), 400

        sender = BulkSender(api_key=api_key, delay=delay)
        report = sender.send_bulk(
            from_addr=from_addr,
            recipients=recipients_raw,
            subject_template=subject,
            body_template=body,
        )

        save_report(report, str(REPORTS_DIR))
        return jsonify(report)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/parse-csv", methods=["POST"])
def api_parse_csv():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        content = file.read().decode("utf-8")
        reader = csv.DictReader(io.StringIO(content))

        if "email" not in (reader.fieldnames or []):
            return jsonify({"error": "CSV must have an 'email' column"}), 400

        recipients = []
        for row in reader:
            row = {k.strip(): v.strip() for k, v in row.items()}
            if row.get("email"):
                recipients.append(row)

        return jsonify({
            "recipients": recipients,
            "count": len(recipients),
            "fields": reader.fieldnames,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/inbox")
def api_inbox():
    emails = []
    for f in sorted(INBOX_DIR.glob("*.json"), reverse=True)[:50]:
        try:
            data = json.loads(f.read_text())
            subject = ""
            for line in data.get("raw", "").splitlines():
                if line.lower().startswith("subject:"):
                    subject = line[8:].strip()
                    break
            emails.append({
                "id": f.stem,
                "from": data.get("from", ""),
                "to": data.get("to", []),
                "subject": subject,
                "timestamp": data.get("timestamp", ""),
                "raw": data.get("raw", ""),
            })
        except Exception:
            continue
    return jsonify(emails)


@app.route("/api/reports")
def api_reports():
    reports = []
    for f in sorted(REPORTS_DIR.glob("*.json"), reverse=True)[:20]:
        try:
            data = json.loads(f.read_text())
            reports.append({
                "id": f.stem,
                "total": data.get("total", 0),
                "sent": data.get("sent", 0),
                "failed": data.get("failed", 0),
                "started_at": data.get("started_at", ""),
            })
        except Exception:
            continue
    return jsonify(reports)


@app.route("/api/config")
def api_config():
    return jsonify({
        "brevo_key_set": bool(os.getenv("BREVO_API_KEY", "")),
        "from_addr": os.getenv("FROM_ADDR", ""),
    })


@app.route("/api/server/start", methods=["POST"])
def api_server_start():
    global _smtp_server, _smtp_controller
    try:
        port = int(request.json.get("port", 1025))
        if _smtp_controller:
            return jsonify({"status": "already_running", "port": port})
        _smtp_server = SMTPServer(host="0.0.0.0", port=port)
        _smtp_controller = Controller(
            _smtp_server.handler, hostname="0.0.0.0", port=port
        )
        _smtp_controller.start()
        return jsonify({"status": "started", "port": port})
    except Exception as e:
        _smtp_controller = None
        return jsonify({"error": str(e)}), 500


@app.route("/api/server/stop", methods=["POST"])
def api_server_stop():
    global _smtp_controller
    if _smtp_controller:
        _smtp_controller.stop()
        _smtp_controller = None
        return jsonify({"status": "stopped"})
    return jsonify({"status": "not_running"})


@app.route("/api/server/status")
def api_server_status():
    return jsonify({"running": _smtp_controller is not None})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
