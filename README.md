# ClickCuts Agent

Agentic Cinema Hackathon — ClickHouse track.

An agent that recommends which narrative structure and thinker persona the next
[Life Interpreter](https://lifeinterp.hun-is.com) shorts episode should use, grounded
in real ClickHouse queries over past episode retention/performance data — not a
guess, not a static rule, an actual tool-calling agent reading real analytics.

**Live demo:** https://clickcuts-agent-802273971180.us-central1.run.app/

**Trailer (3 min, real unstaged demo session):** _link TBD after upload_

## What it does

Each Life Interpreter episode answers a viewer question through one thinker persona
(Nietzsche, Buddha, Jung, Confucius) using one of three narrative card structures:

- **A** — interpretation-first
- **B** — context-first
- **C** — counterpoint-first

The agent is asked things like *"Which structure should the next episode use?"* or
*"Why does Structure C outperform on retention?"* and answers by calling ClickHouse
tools over real per-episode stats — it never states a number it didn't just query for.

## Architecture

```
Cloud Run (webui/)               Vertex AI Agent Engine        Cloud Run
  Flask, thin client        →    shorts_studio_agent.py    →   mcp-clickhouse
  calls stream_query()           (Google ADK, gemini-2.5-flash)  (official runtime)
                                  4 fixed tools in clickhouse_tools.py    ↓
                                                                    ClickHouse Cloud
```

- **`webui/`** — minimal Flask UI on Cloud Run. Thin client only — calls the already-deployed
  Agent Engine instance via `stream_query()` and renders the conversation.
- **`agent/`** — the ADK agent (`shorts_studio_agent.py`) and its 4 fixed, parameterized
  ClickHouse tools (`clickhouse_tools.py`): `get_structure_performance`,
  `get_thinker_performance`, `get_structure_by_thinker`, `get_retention_curve(video_key)`.
  No `execute_sql` / free-form-query tool — the LLM only ever calls these four signatures.
  `deploy.py` ships it to Agent Engine (`reasoningEngines/4789008106929520640`,
  project `802273971180`, `us-central1`).
- **`mcp_clickhouse/`** — Dockerfile for the official
  [`mcp-clickhouse`](https://github.com/ClickHouse/mcp-clickhouse) server, run as its own
  always-on Cloud Run service. The agent talks to ClickHouse only through this MCP server's
  `run_query` tool over bearer-token auth — it never holds the ClickHouse password itself.
  `clickhouse_tools.py`'s four functions stay a fixed, parameterized surface for the LLM;
  only their internal implementation goes through MCP. The one caller-controlled value
  (`video_key` in `get_retention_curve`) is validated against `^[a-z]+_qa_[0-9]+$` before
  it's interpolated into SQL, since mcp-clickhouse's `run_query` doesn't expose ClickHouse's
  native `{name:Type}` parameter binding over MCP.
- **`schema.sql`** / **`extract_and_load.py`** — ClickHouse schema (6 `ReplacingMergeTree`
  tables: `videos`, `video_stats_28d`, `video_stats_daily`, `retention_points`,
  `traffic_source`, `subs_daily`) and the one-time loader from YouTube Analytics exports.

## Data notes

- ~35 published episodes, 5 with detailed retention-curve data — small sample, called out
  explicitly in the agent's answers whenever a claim rests on `n_videos <= 2`.
- `median_view_pct` is used over `avg_view_pct_capped` as the primary metric — a few
  low-view episodes have wildly outlier `average_view_percentage` values from the YouTube
  source data, and the median is robust to that.

## Running locally

```bash
cd agent
pip install google-adk google-cloud-aiplatform[agent_engines] mcp==1.29.0
export CLICKHOUSE_MCP_URL=...       # your mcp-clickhouse Cloud Run URL
export CLICKHOUSE_MCP_AUTH_TOKEN=...
python test_local.py
```

`webui/` needs `AGENT_ENGINE_RESOURCE_NAME`, `GOOGLE_CLOUD_PROJECT`,
`GOOGLE_CLOUD_LOCATION` set (or accepts the defaults baked in for this deployment).

No credentials are hardcoded anywhere in this repo — everything above is read from
environment variables at runtime.
