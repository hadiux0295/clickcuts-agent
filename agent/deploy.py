"""Deploy shorts_studio_agent to Vertex AI Agent Engine (reasoningEngines).

Run once verified locally via test_local.py. The agent talks to ClickHouse only through
the mcp-clickhouse MCP server (Cloud Run) — it never holds the ClickHouse password
itself, only the MCP server's bearer token. Both are injected as deploy-time env vars
(never baked into the bundled source).
"""
import os

import vertexai
from vertexai import agent_engines

from shorts_studio_agent import root_agent

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "life-interpreter-2026")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
STAGING_BUCKET = "gs://clickcuts-agent-staging"

vertexai.init(project=PROJECT, location=LOCATION, staging_bucket=STAGING_BUCKET)

remote_agent = agent_engines.create(
    root_agent,
    display_name="clickcuts-shorts-studio-agent",
    description=root_agent.description,
    requirements=[
        "google-adk",
        "google-cloud-aiplatform[agent_engines]",
        "mcp==1.29.0",
        "cloudpickle",
    ],
    extra_packages=["clickhouse_tools.py"],
    env_vars={
        "CLICKHOUSE_MCP_URL": os.environ["CLICKHOUSE_MCP_URL"],
        "CLICKHOUSE_MCP_AUTH_TOKEN": os.environ["CLICKHOUSE_MCP_AUTH_TOKEN"],
    },
)

print("Deployed:", remote_agent.resource_name)
