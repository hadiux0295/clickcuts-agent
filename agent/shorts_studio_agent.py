"""Shorts Studio Agent — Agentic Cinema hackathon (ClickHouse track).

Recommends the narrative structure + thinker for the next Life Interpreter shorts
episode, grounded in real ClickHouse queries over past episode performance
(clickcuts-db). Built with Google ADK; deployable to Vertex AI Agent Engine
(reasoningEngines) via `deploy.py` once verified locally.
"""
from google.adk.agents import Agent

from clickhouse_tools import (
    get_retention_curve,
    get_structure_by_thinker,
    get_structure_performance,
    get_thinker_performance,
)

# Model string verified against this GCP project during hackathon STEP 0 (2026-08-23) —
# do not swap for a recalled/sample model id (CLAUDE.md §9).
MODEL_ID = "gemini-2.5-flash"

root_agent = Agent(
    name="shorts_studio_agent",
    model=MODEL_ID,
    description=(
        "Recommends the narrative structure and thinker persona for the next Life "
        "Interpreter shorts episode, using real ClickHouse retention data."
    ),
    instruction="""
You are the Shorts Studio Agent for Life Interpreter, a philosophy-shorts YouTube
channel. Each episode presents a user question answered through one thinker persona
(Nietzsche, Buddha, Jung, or Confucius) using one of three narrative card structures:
A (interpretation-first), B (context-first), C (counterpoint-first).

When asked to recommend the next episode's structure and/or thinker, you MUST ground
your recommendation in the ClickHouse tools provided — call get_structure_performance
and get_thinker_performance (and get_structure_by_thinker if you want the cross-tab)
before answering. Never guess a number; every performance claim in your answer must
trace back to a tool result.

Sample sizes here are small (dozens of episodes, not thousands) — say so explicitly
when a conclusion rests on a cell with n_videos <= 2, and prefer median_view_pct over
avg_view_pct_capped as the primary metric (it's noted in the tool docs why).

If asked to illustrate a point visually, call get_retention_curve for one specific
episode key — don't use it to compare structures, it only covers 5 of 35 episodes.

Answer format: 1) the recommendation (structure + thinker), 2) the 2-3 data points
that justify it (with numbers), 3) one caveat about sample size or data noise if
relevant. Keep it under 150 words unless asked for more detail.
""",
    tools=[
        get_structure_performance,
        get_thinker_performance,
        get_structure_by_thinker,
        get_retention_curve,
    ],
)
