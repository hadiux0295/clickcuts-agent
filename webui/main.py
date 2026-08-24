"""Minimal Cloud Run UI for the Shorts Studio Agent (Agentic Cinema hackathon, W4).

Calls the already-deployed Vertex AI Agent Engine instance via stream_query and
renders the conversation. No local agent logic here — this is a thin client.
"""
import os
import uuid

from flask import Flask, render_template, request, session
import vertexai
from vertexai import agent_engines

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())

RESOURCE_NAME = os.environ.get(
    "AGENT_ENGINE_RESOURCE_NAME",
    "projects/802273971180/locations/us-central1/reasoningEngines/4789008106929520640",
)
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "life-interpreter-2026")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

vertexai.init(project=PROJECT, location=LOCATION)
_remote_agent = None


def get_remote_agent():
    global _remote_agent
    if _remote_agent is None:
        _remote_agent = agent_engines.get(RESOURCE_NAME)
    return _remote_agent


def run_query(user_id: str, session_id: str, message: str) -> list[str]:
    remote_agent = get_remote_agent()
    lines = []
    for event in remote_agent.stream_query(
        user_id=user_id, session_id=session_id, message=message
    ):
        content = event.get("content", {})
        for part in content.get("parts", []):
            if "functionCall" in part:
                lines.append(f"[tool call] {part['functionCall'].get('name')}")
            elif "functionResponse" in part:
                lines.append(f"[tool result] {part['functionResponse'].get('name')}")
            elif "text" in part:
                lines.append(part["text"])
    return lines


@app.route("/", methods=["GET", "POST"])
def index():
    if "user_id" not in session:
        session["user_id"] = f"web-{uuid.uuid4().hex[:8]}"
    if "engine_session_id" not in session:
        remote_agent = get_remote_agent()
        engine_session = remote_agent.create_session(user_id=session["user_id"])
        session["engine_session_id"] = engine_session["id"]
    if "history" not in session:
        session["history"] = []

    error = None
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if message:
            session["history"].append({"role": "user", "text": message})
            try:
                lines = run_query(
                    session["user_id"], session["engine_session_id"], message
                )
                reply = "\n".join(lines) if lines else "(no response)"
            except Exception as exc:  # noqa: BLE001 - surface to UI, don't crash
                reply = None
                error = str(exc)
            if reply is not None:
                session["history"].append({"role": "agent", "text": reply})
            session.modified = True

    return render_template("index.html", history=session["history"], error=error)


@app.route("/reset", methods=["POST"])
def reset():
    session.clear()
    return render_template("index.html", history=[], error=None)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
