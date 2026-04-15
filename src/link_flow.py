"""
Plaid Link browser authentication flow for production use.

Spins up a local Flask server, opens the Plaid Link UI in the browser,
waits for the user to complete bank authentication, then exchanges the
resulting public token for a permanent access token and shuts down.
"""

import time
import threading
import webbrowser
from pathlib import Path

from dotenv import set_key
from flask import Flask, jsonify, request

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

_INDEX_HTML = """<!DOCTYPE html>
<html>
<head><title>Connect Bank of America</title>
<meta http-equiv="Permissions-Policy" content="encrypted-media=*, accelerometer=*, camera=*, microphone=*">
<style>
  body { font-family: Arial, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; background: #f5f5f5; }
  h1 { color: #1F3864; }
  button { background: #2E75B6; color: white; border: none; padding: 16px 32px; font-size: 18px; border-radius: 8px; cursor: pointer; margin-top: 24px; }
  button:hover { background: #1F3864; }
  button:disabled { background: #999; cursor: not-allowed; }
  #status { margin-top: 24px; font-size: 16px; color: #375623; }
</style>
</head>
<body>
<h1>🏠 Rental Ledger Sync</h1>
<p>Click below to securely connect your Bank of America account via Plaid</p>
<button id="link-btn" onclick="openLink()">Connect Bank of America</button>
<p id="status"></p>
<script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
<script>
async function openLink() {
  document.getElementById('status').innerText = 'Connecting to Plaid...';
  document.getElementById('link-btn').disabled = true;
  try {
    const res = await fetch('/get_link_token');
    const data = await res.json();
    console.log('Token response:', data);
    if (data.error) {
      document.getElementById('status').innerText = '❌ Error: ' + data.error;
      document.getElementById('link-btn').disabled = false;
      return;
    }
    const handler = window.Plaid.create({
      token: data.link_token,
      onSuccess: async (public_token, metadata) => {
        document.getElementById('status').innerText = '✅ Connected! Saving credentials...';
        const resp = await fetch('/exchange_token', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({public_token: public_token})
        });
        const result = await resp.json();
        if (result.status === 'success') {
          document.getElementById('status').innerText = '✅ Bank account connected successfully! You can close this window.';
          document.getElementById('link-btn').style.display = 'none';
        } else {
          document.getElementById('status').innerText = '❌ Token exchange failed: ' + JSON.stringify(result);
        }
      },
      onLoad: () => {
        console.log('Plaid Link loaded successfully');
      },
      onExit: (err, metadata) => {
        document.getElementById('link-btn').disabled = false;
        if (err) {
          console.error('Plaid exit error:', err);
          document.getElementById('status').innerText = '❌ ' + (err.display_message || err.error_message || 'Connection cancelled');
        } else {
          document.getElementById('status').innerText = 'Cancelled. Click the button to try again.';
        }
      },
      onEvent: (eventName, metadata) => {
        console.log('Plaid event:', eventName, metadata);
      }
    });
    handler.open();
  } catch(e) {
    console.error('Error:', e);
    document.getElementById('status').innerText = '❌ Unexpected error: ' + e.message;
    document.getElementById('link-btn').disabled = false;
  }
}
</script>
</body>
</html>"""


def run_link_flow(plaid_client) -> str:
    """
    Open the Plaid Link browser flow and return a production access token.

    Starts a local Flask server on port 5000, opens the browser to it,
    and blocks until the user completes authentication (max 5 minutes).
    The access token is also saved to .env as PLAID_ACCESS_TOKEN.
    """
    token_received = threading.Event()
    result = []

    app = Flask(__name__)
    log = app.logger

    # Silence Flask's default request logging
    import logging
    log.setLevel(logging.ERROR)

    @app.route("/")
    def index():
        return _INDEX_HTML

    @app.route("/get_link_token")
    def get_link_token():
        try:
            token = plaid_client.create_link_token()
            return jsonify({"link_token": token})
        except Exception as e:
            error_msg = str(e)
            print(f"❌ create_link_token error: {error_msg}")
            return jsonify({"error": error_msg}), 500

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/exchange_token", methods=["POST"])
    def exchange_token():
        public_token = request.get_json().get("public_token")
        access_token = plaid_client.exchange_public_token(public_token)
        set_key(str(_ENV_PATH), "PLAID_ACCESS_TOKEN", access_token)
        result.append(access_token)
        token_received.set()
        return jsonify({"status": "success"})

    print("🌐 Starting local server on http://127.0.0.1:5000 ...")
    print("   If browser doesn't open automatically, visit: http://127.0.0.1:5000")

    # Run Flask in a daemon thread so it dies if the main process exits
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False),
        daemon=True,
    ).start()

    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:5000")
    print("Opening browser... Complete the Bank of America login to continue.")

    if not token_received.wait(timeout=300):
        raise TimeoutError("Browser authentication timed out after 5 minutes")

    return result[0]
