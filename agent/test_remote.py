"""Smoke test the deployed Agent Engine instance (not local)."""
import os

import vertexai
from vertexai import agent_engines

RESOURCE_NAME = "projects/802273971180/locations/us-central1/reasoningEngines/4789008106929520640"

vertexai.init(
    project=os.environ.get("GOOGLE_CLOUD_PROJECT", "life-interpreter-2026"),
    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
)

remote_agent = agent_engines.get(RESOURCE_NAME)

session = remote_agent.create_session(user_id="hun")
for event in remote_agent.stream_query(
    user_id="hun",
    session_id=session["id"],
    message="Which structure should the next episode use? Ground it in the data, keep it short.",
):
    content = event.get("content", {})
    for part in content.get("parts", []):
        if "functionCall" in part:
            print("[TOOL CALL]", part["functionCall"].get("name"))
        if "functionResponse" in part:
            print("[TOOL RESULT]", part["functionResponse"].get("name"), str(part["functionResponse"].get("response"))[:200])
        if "text" in part:
            print("[TEXT]", part["text"])
