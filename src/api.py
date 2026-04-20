import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request

ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_PATH)

sys.path.insert(0, os.path.dirname(__file__))

import main as sync_main

app         = Flask(__name__)
sync_lock   = threading.Lock()
sync_status = {"running": False, "last_run": None, "last_result": None}


def _run_sync_thread(from_date=None):
    try:
        sync_status["running"] = True
        result = sync_main.run_sync(from_date=from_date)
        sync_status["last_result"] = result
        sync_status["last_run"]    = datetime.now(timezone.utc).isoformat()
    except Exception as e:
        sync_status["last_result"] = {"error": str(e)}
    finally:
        sync_status["running"] = False
        sync_lock.release()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":       "healthy",
        "service":      "rental-ledger-sync",
        "environment":  os.getenv("RAILWAY_ENVIRONMENT", "local"),
        "timestamp":    datetime.now(timezone.utc).isoformat(),
        "sync_running": sync_status["running"],
        "last_run":     sync_status["last_run"],
    })


@app.route("/sync", methods=["POST"])
def sync():
    if not sync_lock.acquire(blocking=False):
        return jsonify({"status": "busy", "message": "Sync already in progress"}), 409

    from_date = request.get_json(silent=True).get("from_date") if request.is_json else None

    thread = threading.Thread(target=_run_sync_thread, args=(from_date,), daemon=True)
    thread.start()

    return jsonify({
        "status":    "started",
        "message":   "Sync started in background",
        "from_date": from_date or "last 3 days (default)",
    })


@app.route("/sync/test", methods=["POST"])
def sync_test():
    results = {}

    try:
        from plaid_client import PlaidClient
        client       = PlaidClient()
        access_token = os.getenv("PLAID_ACCESS_TOKEN", "")
        valid        = client.verify_access_token(access_token) if access_token else False
        results["plaid"] = "connected" if valid else "token_missing_or_invalid"
    except Exception as e:
        results["plaid"] = f"error: {e}"

    try:
        from drive_sync import get_drive_service
        get_drive_service()
        results["drive"] = "connected"
    except Exception as e:
        results["drive"] = f"error: {e}"

    all_ok           = all(v == "connected" for v in results.values())
    results["status"] = "ok" if all_ok else "degraded"

    return jsonify(results)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
