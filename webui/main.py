"""Minimal Cloud Run UI for the Shorts Studio Agent (Agentic Cinema hackathon).

Calls the already-deployed Vertex AI Agent Engine instance via stream_query and
renders the conversation. No local agent logic here — this is a thin client.

Conversation history is kept server-side (in-process, keyed by a small cookie
session id) rather than inside the Flask session cookie: agent replies are long
enough to blow the ~4KB cookie limit after a few turns, which silently drops the
whole conversation. The service is deployed with min/max instances = 1, so a
single in-process store is sufficient for demo/judging traffic.
"""
import os
import threading
import time
import uuid

from flask import Flask, jsonify, render_template, request, session
import vertexai
from vertexai import agent_engines

app = Flask(__name__)
# Must be stable across restarts/instances, otherwise every cold start invalidates
# every visitor's cookie — set FLASK_SECRET_KEY in the Cloud Run env.
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24).hex()

RESOURCE_NAME = os.environ.get(
    "AGENT_ENGINE_RESOURCE_NAME",
    "projects/802273971180/locations/us-central1/reasoningEngines/4789008106929520640",
)
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "life-interpreter-2026")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
MAX_TURNS = 30  # per conversation, keeps memory bounded

vertexai.init(project=PROJECT, location=LOCATION)
_remote_agent = None
_lock = threading.Lock()
# user_id -> {"engine_session_id": str, "history": [ {role, text, tools, retention} ]}
_conversations: dict[str, dict] = {}


def get_remote_agent():
    global _remote_agent
    if _remote_agent is None:
        _remote_agent = agent_engines.get(RESOURCE_NAME)
    return _remote_agent


def get_conversation() -> tuple[str, dict]:
    if "user_id" not in session:
        session["user_id"] = f"web-{uuid.uuid4().hex[:8]}"
    user_id = session["user_id"]
    with _lock:
        conv = _conversations.get(user_id)
    if conv is None:
        remote_agent = get_remote_agent()
        engine_session = remote_agent.create_session(user_id=user_id)
        conv = {"engine_session_id": engine_session["id"], "history": []}
        with _lock:
            _conversations[user_id] = conv
    return user_id, conv


def run_query(user_id: str, session_id: str, message: str) -> dict:
    """Returns {"text": str, "tools": [names], "retention": dict|None}."""
    remote_agent = get_remote_agent()
    texts, tools, retention = [], [], None
    for event in remote_agent.stream_query(
        user_id=user_id, session_id=session_id, message=message
    ):
        content = event.get("content", {})
        for part in content.get("parts", []):
            # Agent Engine serializes ADK parts in snake_case (function_call); older
            # SDKs used camelCase — accept both.
            fc = part.get("function_call") or part.get("functionCall")
            fr = part.get("function_response") or part.get("functionResponse")
            if fc:
                tools.append(fc.get("name"))
            elif fr:
                resp = fr.get("response") or {}
                # Surface the one tool whose output is meant to be *seen*, not just read.
                if fr.get("name") == "get_retention_curve" and isinstance(resp, dict):
                    if "points" in resp:
                        retention = {
                            "video_key": resp.get("video_key"),
                            "title": resp.get("title"),
                            "points": resp.get("points"),
                        }
            elif "text" in part:
                texts.append(part["text"])
    return {"text": "\n".join(texts).strip() or "(no response)", "tools": tools, "retention": retention}


@app.route("/", methods=["GET"])
def index():
    _, conv = get_conversation()
    return render_template("index.html", history=conv["history"])


@app.route("/api/chat", methods=["POST"])
def api_chat():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"error": "empty message"}), 400
    user_id, conv = get_conversation()
    if len(conv["history"]) >= MAX_TURNS * 2:
        return jsonify({"error": "conversation is long — press Reset to start a new one"}), 429
    conv["history"].append({"role": "user", "text": message})
    t0 = time.time()
    try:
        result = run_query(user_id, conv["engine_session_id"], message)
    except Exception as exc:  # noqa: BLE001 - surface to UI, don't crash
        conv["history"].pop()
        return jsonify({"error": str(exc)}), 502
    entry = {"role": "agent", **result}
    conv["history"].append(entry)
    return jsonify({**entry, "elapsed_s": round(time.time() - t0, 1)})


@app.route("/reset", methods=["POST"])
def reset():
    user_id = session.get("user_id")
    if user_id:
        with _lock:
            _conversations.pop(user_id, None)
    session.clear()
    return jsonify({"ok": True})


@app.route("/healthz", methods=["GET"])
def healthz():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
