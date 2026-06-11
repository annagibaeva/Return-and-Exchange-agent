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

import os
import uuid

import anthropic
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template_string, request, session

from agent import run_agent
from supervisor import supervised_reply

load_dotenv()

app = Flask(__name__)
# Local demo secret; fine for a single-user dev server. Override via env if set.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "returns-exchange-demo-secret")

# Module-level in-memory store: session id -> conversation list.
# Each conversation is a list of {"role": "user"|"assistant", "content": <str>}.
_conversations = {}

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
    return _conversations.setdefault(sid, [])


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
        <div class="sub">Singapore Apparel &middot; supervised agent demo</div>
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


@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Empty message."}), 400

    conversation = _get_conversation()
    try:
        client = get_client()
        # 1. append the user's message
        conversation.append({"role": "user", "content": message})
        # 2. primary agent drafts a reply (with tool calls)
        draft, trace = run_agent(conversation, client=client)
        # 3. supervisor audits the draft before it reaches the customer
        reply, verdict = supervised_reply(conversation, draft, trace, client=client)
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
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        if conversation and conversation[-1].get("role") == "user":
            conversation.pop()
        return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/reset", methods=["POST"])
def reset():
    sid = session.get("sid")
    if sid:
        _conversations[sid] = []
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
