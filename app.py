"""
app.py — a single-file Flask chat UI for the returns-and-exchange agent.

Serves a small browser chat page at `/` and runs the full per-turn pipeline
behind it: the primary agent (run_agent) drafts a reply, then the supervisor
(supervised_reply) audits it before anything reaches the customer. The
conversation that the browser sees stores the SUPERVISED reply, so history
stays faithful to what a customer would actually receive.

Run:
    pip install -r requirements.txt
    python app.py
Then open http://localhost:5000 in a browser.

Conversation state is kept server-side in memory, keyed by a per-browser
session id. This is a local single-user demo; it is intentionally simple and
not hardened against concurrency.
"""

import json
import logging
import os
import secrets
import sys
import time
import uuid
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from flask import Flask, jsonify, make_response, render_template_string, request, session

from agent import run_agent
from supervisor import supervised_reply

load_dotenv()

logger = logging.getLogger(__name__)

# Reject oversized payloads early to limit cost/DoS exposure.
MAX_MESSAGE_CHARS = 4000
MAX_CONVERSATIONS = int(os.environ.get("MAX_CONVERSATIONS", "100"))
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "3600"))

# Optional API key for state-changing endpoints. When unset, auth is skipped.
CHAT_API_KEY = os.environ.get("CHAT_API_KEY")

# Per-IP rate limit for /chat (in-memory; resets on process restart).
_RATE_LIMIT_WINDOW_SEC = 60
_RATE_LIMIT_MAX_REQUESTS = 10
_rate_limit_hits: dict[str, list[float]] = defaultdict(list)

app = Flask(__name__)

# Use a stable secret from the environment in any real deployment. Falling back
# to a per-process random secret keeps cookies unforgeable for a local demo
# (sessions simply don't survive a restart), instead of shipping a hardcoded,
# publicly known secret that would let anyone forge session cookies.
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

# Harden the session cookie. HttpOnly blocks JS access; SameSite mitigates CSRF
# on the state-changing endpoints; Secure can be forced on when served over TLS.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_COOKIE_SECURE", "").lower() == "true",
    MAX_CONTENT_LENGTH=64 * 1024,
)

class ConversationStore:
    """Bounded in-memory store: session id -> conversation list with TTL/LRU."""

    def __init__(self, max_conversations: int, ttl_seconds: int) -> None:
        self._max = max_conversations
        self._ttl = ttl_seconds
        self._sessions: dict[str, dict] = {}

    def get(self, sid: str) -> list:
        """Return the conversation for sid, creating an empty list if needed."""
        self.evict_expired()
        entry = self._sessions.get(sid)
        if entry is None:
            self.evict_lru()
            entry = {"messages": [], "last_accessed": time.time()}
            self._sessions[sid] = entry
        else:
            entry["last_accessed"] = time.time()
        return entry["messages"]

    def set(self, sid: str, conversation: list) -> None:
        """Replace the conversation list for sid."""
        self.evict_expired()
        self._sessions[sid] = {
            "messages": conversation,
            "last_accessed": time.time(),
        }
        while len(self._sessions) > self._max:
            self.evict_lru()

    def reset(self, sid: str) -> None:
        """Clear the conversation for sid."""
        entry = self._sessions.get(sid)
        if entry is not None:
            entry["messages"] = []
            entry["last_accessed"] = time.time()

    def evict_expired(self) -> None:
        """Remove sessions that have exceeded the TTL since last access."""
        cutoff = time.time() - self._ttl
        for sid in [
            sid
            for sid, entry in self._sessions.items()
            if entry["last_accessed"] < cutoff
        ]:
            del self._sessions[sid]

    def evict_lru(self) -> None:
        """Evict the least-recently accessed session when at capacity."""
        if len(self._sessions) < self._max:
            return
        oldest_sid = min(
            self._sessions,
            key=lambda sid: self._sessions[sid]["last_accessed"],
        )
        del self._sessions[oldest_sid]


_store = ConversationStore(MAX_CONVERSATIONS, SESSION_TTL_SECONDS)

_DATA = Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def _load_orders():
    with open(_DATA / "orders.json", encoding="utf-8") as f:
        return json.load(f)


def _verify_order_email(order_id: str, email: str) -> str | None:
    """Return the order's canonical email when it matches (case-insensitive)."""
    orders = _load_orders()
    oid = order_id.strip().upper()
    order = orders.get(oid)
    if not order:
        return None
    if email.strip().lower() != order["customer_email"].strip().lower():
        return None
    return order["customer_email"]

# Lazily-created Anthropic client. We do NOT create it at import time so this
# module imports cleanly even when no ANTHROPIC_API_KEY is set.
_client = None


def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _client


def _get_conversation():
    """Return the conversation list for the current browser session, creating
    a session id and an empty list on first use."""
    sid = session.get("sid")
    if not sid:
        sid = uuid.uuid4().hex
        session["sid"] = sid
    return _store.get(sid)


def _client_ip() -> str:
    return request.remote_addr or "unknown"


def _unauthorized_response():
    return jsonify({"error": "Unauthorized."}), 401


def _require_api_key():
    """Return an error response when CHAT_API_KEY is set but the header is wrong."""
    if not CHAT_API_KEY:
        return None
    provided = request.headers.get("X-API-Key", "")
    if not secrets.compare_digest(provided, CHAT_API_KEY):
        return _unauthorized_response()
    return None


def _rate_limit_exceeded() -> bool:
    """Return True when this client IP has exceeded the /chat rate limit."""
    ip = _client_ip()
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SEC
    hits = _rate_limit_hits[ip]
    hits[:] = [t for t in hits if t > window_start]
    if len(hits) >= _RATE_LIMIT_MAX_REQUESTS:
        return True
    hits.append(now)
    return False


def _no_store(response):
    resp = make_response(response)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _validate_startup_config() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    if host != "0.0.0.0":
        return
    missing = []
    if not CHAT_API_KEY:
        missing.append("CHAT_API_KEY")
    if not os.environ.get("FLASK_SECRET_KEY"):
        missing.append("FLASK_SECRET_KEY")
    if missing:
        sys.exit(
            "Error: HOST is 0.0.0.0 but required environment variables are missing: "
            + ", ".join(missing)
        )


@app.after_request
def _cache_control(response):
    if request.endpoint in ("index", "chat"):
        response.headers["Cache-Control"] = "no-store"
    return response


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Returns &amp; Exchange Assistant</title>
<style>
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    background: #eef1f6;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    color: #1d2530;
  }
  .panel {
    width: 100%;
    max-width: 640px;
    height: 80vh;
    max-height: 760px;
    background: #fff;
    border-radius: 16px;
    box-shadow: 0 12px 40px rgba(20, 30, 50, 0.15);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    background: #1f2a44;
    color: #fff;
  }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header .sub { font-size: 12px; opacity: 0.7; margin-top: 2px; }
  #newchat {
    background: rgba(255,255,255,0.12);
    color: #fff;
    border: 1px solid rgba(255,255,255,0.25);
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
    cursor: pointer;
  }
  #newchat:hover { background: rgba(255,255,255,0.22); }
  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    background: #f7f8fb;
  }
  .row { display: flex; flex-direction: column; max-width: 80%; }
  .row.user { align-self: flex-end; align-items: flex-end; }
  .row.agent { align-self: flex-start; align-items: flex-start; }
  .bubble {
    padding: 10px 14px;
    border-radius: 14px;
    font-size: 14px;
    line-height: 1.45;
    white-space: pre-wrap;
    word-wrap: break-word;
  }
  .row.user .bubble {
    background: #2563eb;
    color: #fff;
    border-bottom-right-radius: 4px;
  }
  .row.agent .bubble {
    background: #fff;
    color: #1d2530;
    border: 1px solid #e3e7ef;
    border-bottom-left-radius: 4px;
  }
  .badge {
    margin-top: 5px;
    font-size: 12px;
    color: #92580a;
    background: #fef3cd;
    border: 1px solid #f6e0a0;
    border-radius: 6px;
    padding: 3px 8px;
  }
  .badge.escalate { color: #8a1c1c; background: #fde2e1; border-color: #f4b8b5; }
  .typing { font-style: italic; color: #7a8499; }
  .error {
    align-self: center;
    color: #8a1c1c;
    background: #fde2e1;
    border: 1px solid #f4b8b5;
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    max-width: 90%;
    text-align: center;
  }
  footer {
    display: flex;
    gap: 8px;
    padding: 14px 16px;
    border-top: 1px solid #e6e9f0;
    background: #fff;
  }
  #input {
    flex: 1;
    border: 1px solid #cfd5e2;
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 14px;
    outline: none;
    font-family: inherit;
  }
  #input:focus { border-color: #2563eb; }
  #input:disabled { background: #f1f3f8; color: #9aa3b5; }
  #send {
    background: #2563eb;
    color: #fff;
    border: none;
    border-radius: 10px;
    padding: 0 18px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
  }
  #send:disabled { background: #9bb4ef; cursor: default; }
</style>
</head>
<body>
  <div class="panel">
    <header>
      <div>
        <h1>Returns &amp; Exchange Assistant</h1>
        <div class="sub">Singapore Apparel &middot; verify with order ID + email</div>
      </div>
      <button id="newchat" type="button">New chat</button>
    </header>
    <div id="messages"></div>
    <footer>
      <input id="input" type="text" placeholder="Type your message..." autocomplete="off">
      <button id="send" type="button">Send</button>
    </footer>
  </div>

<script>
  const messages = document.getElementById("messages");
  const input = document.getElementById("input");
  const send = document.getElementById("send");
  const newchat = document.getElementById("newchat");

  function scrollDown() { messages.scrollTop = messages.scrollHeight; }

  function addMessage(role, text) {
    const row = document.createElement("div");
    row.className = "row " + role;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = text;
    row.appendChild(bubble);
    messages.appendChild(row);
    scrollDown();
    return row;
  }

  function addBadge(row, verdict, reason) {
    const badge = document.createElement("div");
    badge.className = "badge" + (verdict === "ESCALATE" ? " escalate" : "");
    badge.textContent = "Supervisor: " + verdict + (reason ? " — " + reason : "");
    row.appendChild(badge);
    scrollDown();
  }

  function addError(text) {
    const el = document.createElement("div");
    el.className = "error";
    el.textContent = text;
    messages.appendChild(el);
    scrollDown();
  }

  function showTyping() {
    const row = document.createElement("div");
    row.className = "row agent";
    row.id = "typing-row";
    const bubble = document.createElement("div");
    bubble.className = "bubble typing";
    bubble.textContent = "typing…";
    row.appendChild(bubble);
    messages.appendChild(row);
    scrollDown();
  }

  function hideTyping() {
    const row = document.getElementById("typing-row");
    if (row) row.remove();
  }

  function setBusy(busy) {
    input.disabled = busy;
    send.disabled = busy;
    if (!busy) input.focus();
  }

  async function sendMessage() {
    const text = input.value.trim();
    if (!text) return;
    addMessage("user", text);
    input.value = "";
    setBusy(true);
    showTyping();
    try {
      const orderMatch = text.match(/\\b(NW-\\d+)\\b/i);
      const emailMatch = text.match(/[\\w.+-]+@[\\w.-]+\\.\\w+/);
      if (orderMatch && emailMatch) {
        const verifyRes = await fetch("/verify", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            order_id: orderMatch[1],
            email: emailMatch[0]
          })
        });
        const verifyData = await verifyRes.json();
        if (!verifyRes.ok || !verifyData.verified) {
          hideTyping();
          addError(verifyData.error || "Could not verify order ID and email. Please check and try again.");
          setBusy(false);
          return;
        }
      }
      const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text })
      });
      hideTyping();
      const data = await res.json();
      if (!res.ok) {
        addError(data.error || "Something went wrong.");
      } else {
        const row = addMessage("agent", data.reply);
        if (data.verdict && data.verdict !== "PASS") {
          addBadge(row, data.verdict, data.reason || "");
        }
      }
    } catch (err) {
      hideTyping();
      addError("Network error: " + err.message);
    } finally {
      setBusy(false);
    }
  }

  async function resetChat() {
    setBusy(true);
    try {
      await fetch("/reset", { method: "POST" });
    } catch (err) { /* ignore */ }
    messages.innerHTML = "";
    setBusy(false);
  }

  send.addEventListener("click", sendMessage);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  newchat.addEventListener("click", resetChat);
  input.focus();
</script>
</body>
</html>
"""


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True})


@app.route("/")
def index():
    return _no_store(render_template_string(PAGE))


@app.route("/verify", methods=["POST"])
def verify():
    """Verify order ownership and bind identity to the server session."""
    auth_error = _require_api_key()
    if auth_error:
        return auth_error

    data = request.get_json(silent=True) or {}
    order_id = (data.get("order_id") or "").strip()
    email = (data.get("email") or "").strip()
    if not order_id or not email:
        return jsonify({"verified": False, "error": "order_id and email required."}), 400

    canonical = _verify_order_email(order_id, email)
    if canonical:
        session["customer_email"] = canonical
        return jsonify({"verified": True})
    return jsonify({"verified": False})


@app.route("/chat", methods=["POST"])
def chat():
    auth_error = _require_api_key()
    if auth_error:
        return auth_error
    if _rate_limit_exceeded():
        return jsonify({"error": "Rate limit exceeded. Try again later."}), 429

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Empty message."}), 400
    if len(message) > MAX_MESSAGE_CHARS:
        return jsonify({
            "error": f"Message too long (max {MAX_MESSAGE_CHARS} characters)."
        }), 413

    conversation = _get_conversation()
    try:
        client = get_client()
        # 1. append the user's message
        conversation.append({"role": "user", "content": message})
        # 2. primary agent drafts a reply (with tool calls)
        draft, trace = run_agent(
            conversation,
            client=client,
            session_customer_email=session.get("customer_email"),
            allow_chat_email_fallback=False,
        )
        # 3. supervisor audits the draft before it reaches the customer
        reply, verdict = supervised_reply(
            conversation,
            draft,
            trace,
            client=client,
            session_customer_email=session.get("customer_email"),
            allow_chat_email_fallback=False,
        )
        # 4. store the SUPERVISED reply (what the customer actually sees)
        conversation.append({"role": "assistant", "content": reply})
        # 5. return the supervised reply and verdict to the browser
        return jsonify({
            "reply": reply,
            "verdict": verdict.get("verdict", "PASS"),
            "reason": verdict.get("reason", ""),
        })
    except KeyError:
        # Most likely a missing ANTHROPIC_API_KEY when creating the client.
        # Roll back the just-appended user turn so retrying after fixing the
        # key doesn't double up the message.
        if conversation and conversation[-1].get("role") == "user":
            conversation.pop()
        return jsonify({
            "error": "ANTHROPIC_API_KEY is not set. Add it to your environment "
                     "or .env file and restart the server."
        }), 500
    except Exception:  # noqa: BLE001 - keep the demo server responsive
        if conversation and conversation[-1].get("role") == "user":
            conversation.pop()
        # Log the full error server-side; return a generic message so internal
        # details (stack types, paths, upstream errors) aren't leaked to clients.
        logger.exception("Unhandled error while processing chat turn")
        return jsonify({"error": "Something went wrong. Please try again."}), 500


@app.route("/reset", methods=["POST"])
def reset():
    auth_error = _require_api_key()
    if auth_error:
        return auth_error

    sid = session.get("sid")
    if sid:
        _store.reset(sid)
    session.pop("customer_email", None)
    return jsonify({"ok": True})


if __name__ == "__main__":
    _validate_startup_config()
    # debug=True exposes the interactive Werkzeug debugger (arbitrary code
    # execution if reachable) and must never be on by default. Opt in explicitly
    # via FLASK_DEBUG=1 for local development only.
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes"}
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(debug=debug, host=host, port=int(os.environ.get("PORT", "5000")))
