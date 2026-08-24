"""Fixed, parameterized ClickHouse queries against clickcuts-db — no free-form SQL tool.

Queries run through the official `mcp-clickhouse` MCP server (Cloud Run, streamable
HTTP) rather than a direct HTTPS connection to ClickHouse — this satisfies the
hackathon's "use the official ClickHouse MCP server runtime" requirement. The LLM never
sees this module's internals: it only calls the 4 functions below, each of which builds
its own fixed SQL and forwards it to the MCP server's `run_query` tool. The MCP server
holds the real ClickHouse credentials; this process only holds a bearer token for it.

mcp-clickhouse's `run_query` takes a single opaque SQL string — unlike the old direct
HTTPS path, it does not expose ClickHouse's native `{name:Type}` bound-parameter syntax
over the MCP wire. The only caller-influenced value here is `get_retention_curve`'s
video_key, so it is validated against a strict whitelist pattern before being
string-interpolated into SQL (see _VIDEO_KEY_RE) — never accept an unvalidated value
into a query string.
"""
import asyncio
import concurrent.futures
import json
import os
import re

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.environ["CLICKHOUSE_MCP_URL"]  # e.g. https://.../mcp — NO trailing slash
MCP_AUTH_TOKEN = os.environ["CLICKHOUSE_MCP_AUTH_TOKEN"]

# thinker_qa_N, matches the key format written by shorts_test/gen_qa.mjs.
_VIDEO_KEY_RE = re.compile(r"^[a-z]+_qa_[0-9]+$")


async def _run_query_async(sql: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {MCP_AUTH_TOKEN}"}
    async with streamablehttp_client(MCP_URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("run_query", {"query": sql})
            text = result.content[0].text
            if result.isError:
                raise RuntimeError(f"mcp-clickhouse run_query error: {text}")
            payload = json.loads(text)
            columns = payload["columns"]
            return [dict(zip(columns, row)) for row in payload["rows"]]


def _query_json(sql: str) -> list[dict]:
    """Runs synchronously. ADK calls these tool functions directly on its own running
    event loop (not off-loaded to a thread), so a plain asyncio.run() here would raise
    "cannot be called from a running event loop" — run the MCP call in a dedicated
    thread with its own event loop instead, and block the caller for the result."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(_run_query_async(sql))).result()


def get_structure_performance() -> dict:
    """Compare narrative-card structure variants (A=interpretation, B=context, C=counterpoint)
    by median audience-retention percentage across published episodes.

    Only episodes that were generated with a structure variant are included (older
    pre-variant episodes and non-QA content are excluded). Median is used instead of a
    plain average because a handful of very-low-view episodes have wildly inflated
    view-percentage values (YouTube replay artifacts on tiny sample sizes) that would
    otherwise dominate the ranking.

    Returns:
        A dict with key "structures": a list of rows, each
        {structure, structure_name, n_videos, total_views, median_view_pct, avg_view_pct_capped},
        sorted by median_view_pct descending (best-retaining structure first).
    """
    rows = _query_json("""
        SELECT v.structure AS structure,
               any(v.structure_name) AS structure_name,
               count() AS n_videos,
               sum(s.views) AS total_views,
               round(median(s.average_view_percentage), 2) AS median_view_pct,
               round(avg(least(s.average_view_percentage, 100)), 2) AS avg_view_pct_capped
        FROM video_stats_28d s FINAL
        JOIN videos v FINAL ON v.video_id = s.video_id
        WHERE v.structure != ''
        GROUP BY v.structure
        ORDER BY median_view_pct DESC
    """)
    return {"structures": rows}


def get_thinker_performance() -> dict:
    """Compare the four thinker personas (nietzsche/buddha/jung/confucius) by median
    audience-retention percentage and total views across all published episodes for
    that persona.

    Returns:
        A dict with key "thinkers": a list of rows, each
        {thinker, n_videos, total_views, median_view_pct, avg_view_pct_capped},
        sorted by median_view_pct descending.
    """
    rows = _query_json("""
        SELECT v.thinker AS thinker,
               count() AS n_videos,
               sum(s.views) AS total_views,
               round(median(s.average_view_percentage), 2) AS median_view_pct,
               round(avg(least(s.average_view_percentage, 100)), 2) AS avg_view_pct_capped
        FROM video_stats_28d s FINAL
        JOIN videos v FINAL ON v.video_id = s.video_id
        WHERE v.thinker != 'mixed'
        GROUP BY v.thinker
        ORDER BY median_view_pct DESC
    """)
    return {"thinkers": rows}


def get_structure_by_thinker() -> dict:
    """Cross-tabulate structure variant x thinker persona, to check whether the best
    structure differs per thinker (rather than one structure being universally best).
    Small per-cell sample sizes (n_videos) are included so the caller can judge
    confidence — a cell with n_videos=1 should not be treated as a strong signal.

    Returns:
        A dict with key "cells": a list of rows, each
        {thinker, structure, n_videos, total_views, median_view_pct}.
    """
    rows = _query_json("""
        SELECT v.thinker AS thinker,
               v.structure AS structure,
               count() AS n_videos,
               sum(s.views) AS total_views,
               round(median(s.average_view_percentage), 2) AS median_view_pct
        FROM video_stats_28d s FINAL
        JOIN videos v FINAL ON v.video_id = s.video_id
        WHERE v.structure != '' AND v.thinker != 'mixed'
        GROUP BY v.thinker, v.structure
        ORDER BY v.thinker, median_view_pct DESC
    """)
    return {"cells": rows}


def get_retention_curve(video_key: str) -> dict:
    """Fetch the normalized retention curve (0-100% of video duration on the x-axis,
    audience-remaining ratio on the y-axis) for one specific published episode, looked
    up by its short key (e.g. "buddha_qa_8"), for illustrating where viewers drop off.

    Only 5 of the 35 published episodes have a retention curve on file (YouTube only
    exposes this for videos crossing a minimum-views threshold) — call
    get_structure_performance / get_thinker_performance first to decide which
    conclusions to draw; use this tool only to illustrate one, not to compare structures.

    Args:
        video_key: the short key of the video, e.g. "buddha_qa_8".

    Returns:
        A dict {video_key, video_id, title, points: [[t_ratio, watch_ratio], ...]},
        or {"error": "..."} with the list of available keys if not found.
    """
    if not _VIDEO_KEY_RE.match(video_key):
        return {"error": f"invalid video_key format: {video_key!r}"}

    rows = _query_json(f"""
        SELECT v.video_id AS video_id, v.key AS key, v.title AS title
        FROM videos v FINAL
        WHERE v.key = '{video_key}'
        LIMIT 1
    """)
    if not rows:
        available = _query_json("""
            SELECT DISTINCT v.key AS key FROM retention_points r FINAL
            JOIN videos v FINAL ON v.video_id = r.video_id
        """)
        return {"error": f"no video with key {video_key!r}", "available_keys": [r["key"] for r in available]}
    video_id = rows[0]["video_id"]
    points = _query_json(f"""
        SELECT t_ratio, watch_ratio FROM retention_points FINAL
        WHERE video_id = '{video_id}' ORDER BY t_ratio
    """)
    if not points:
        available = _query_json("""
            SELECT DISTINCT v.key AS key FROM retention_points r FINAL
            JOIN videos v FINAL ON v.video_id = r.video_id
        """)
        return {"error": f"no retention curve on file for {video_key!r}", "available_keys": [r["key"] for r in available]}
    return {
        "video_key": video_key,
        "video_id": video_id,
        "title": rows[0]["title"],
        "points": [[p["t_ratio"], p["watch_ratio"]] for p in points],
    }
