#!/usr/bin/env python3
"""Extract LI shorts analytics (JSON + CSV) into clickcuts-db normalized tables.

Read-only against the live monorepo data. Writes only to ClickHouse Cloud
(credentials from temp/agentic_cinema_hackathon/CLICKHOUSE_CREDENTIALS.md,
passed via env vars — never hardcoded here).
"""
import csv
import json
import os
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
SHORTS_DIR = REPO_ROOT / "apps/life_interpreter/scripts/shorts_test"
ANALYTICS_DIR = SHORTS_DIR / "analytics"
JSON_REPORT = ANALYTICS_DIR / "yt_analytics_report.20260821.json"
VIEWS_CSV = ANALYTICS_DIR / "views_log.csv"

QA_FILES = ["qa_nietzsche.json", "qa_buddha.json", "qa_jung.json", "qa_confucius.json"]

CH_HOST = os.environ["CLICKHOUSE_HOST"]
CH_PORT = os.environ.get("CLICKHOUSE_PORT", "8443")
CH_USER = os.environ.get("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.environ["CLICKHOUSE_PASSWORD"]
CH_DATABASE = os.environ.get("CLICKHOUSE_DATABASE", "default")
CH_URL = f"https://{CH_HOST}:{CH_PORT}/"


def ch_exec(query: str, tsv_body: str | None = None):
    """Run a DDL/SELECT via `query=`, or an `INSERT ... FORMAT TSV` with tsv_body as the payload."""
    if tsv_body is not None:
        resp = requests.post(
            CH_URL,
            params={"database": CH_DATABASE, "query": query},
            data=tsv_body.encode("utf-8"),
            auth=(CH_USER, CH_PASSWORD),
            timeout=60,
        )
    else:
        resp = requests.post(
            CH_URL,
            params={"database": CH_DATABASE},
            data=query.encode("utf-8"),
            auth=(CH_USER, CH_PASSWORD),
            timeout=30,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"ClickHouse error {resp.status_code}: {resp.text[:2000]}")
    return resp.text


def tsv_escape(v):
    if v is None:
        return "\\N"
    s = str(v)
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def load_json():
    return json.loads(JSON_REPORT.read_text())


def load_csv_rows():
    with open(VIEWS_CSV, newline="") as f:
        return list(csv.DictReader(f))


def build_structure_map():
    """key ('<thinker>_qa_<n>') -> (structure, structure_name), from the live qa_<t>.json files.

    Read-only. Array index N (0-based) corresponds to key '<thinker>_qa_{N+1}' — confirmed
    against upload_meta.json keys, which are generated the same way by sync_upload_meta.mjs.
    Items predating the 2026-07-26 structure-variant rollout (CLAUDE.md §9.13) have no
    'structure' field and are left out of the map (videos table default '' applies).
    """
    smap = {}
    for fname in QA_FILES:
        path = SHORTS_DIR / fname
        if not path.exists():
            continue
        thinker = fname.removeprefix("qa_").removesuffix(".json")
        items = json.loads(path.read_text())
        for i, item in enumerate(items):
            if item.get("structure"):
                smap[f"{thinker}_qa_{i + 1}"] = (item["structure"], item.get("structureName", ""))
    return smap


def build_videos(report, csv_rows, structure_map):
    videos = {}
    for row in csv_rows:
        videos[row["id"]] = {
            "video_id": row["id"],
            "key": row["key"],
            "thinker": row["thinker"],
            "category": row["category"],
            "title": row["title"],
        }
    for row in report["perVideoRows"]:
        vid = row["videoId"]
        if vid not in videos:
            videos[vid] = {
                "video_id": vid,
                "key": row["key"],
                "thinker": row["thinker"],
                "category": "",
                "title": "",
            }
    for v in videos.values():
        structure, structure_name = structure_map.get(v["key"], ("", ""))
        v["structure"] = structure
        v["structure_name"] = structure_name
    return list(videos.values())


def main():
    report = load_json()
    csv_rows = load_csv_rows()
    snapshot_date = report["generatedAtUtc"][:10]

    print("Applying schema...")
    schema_sql = (Path(__file__).parent / "schema.sql").read_text()
    for stmt in [s.strip() for s in schema_sql.split(";") if s.strip()]:
        ch_exec(stmt)
    # Idempotent for the pre-existing videos table from the first W1/W2 run (CREATE IF NOT EXISTS
    # above is a no-op on it since it already exists without these columns).
    ch_exec("ALTER TABLE videos ADD COLUMN IF NOT EXISTS structure String DEFAULT ''")
    ch_exec("ALTER TABLE videos ADD COLUMN IF NOT EXISTS structure_name String DEFAULT ''")

    structure_map = build_structure_map()
    videos = build_videos(report, csv_rows, structure_map)
    n_with_structure = sum(1 for v in videos if v["structure"])
    print(f"videos: {len(videos)} rows ({n_with_structure} with a structure variant)")
    tsv = "\n".join(
        "\t".join(tsv_escape(v[c]) for c in ("video_id", "key", "thinker", "category", "title", "structure", "structure_name"))
        for v in videos
    )
    ch_exec("INSERT INTO videos (video_id, key, thinker, category, title, structure, structure_name) FORMAT TSV", tsv)

    rows = report["perVideoRows"]
    print(f"video_stats_28d: {len(rows)} rows")
    tsv = "\n".join(
        "\t".join(tsv_escape(x) for x in (
            r["videoId"], snapshot_date, r["views"], r["estimatedMinutesWatched"],
            r["averageViewDuration"], r["averageViewPercentage"], r["subscribersGained"],
        ))
        for r in rows
    )
    ch_exec(
        "INSERT INTO video_stats_28d (video_id, snapshot_date, views, estimated_minutes_watched, "
        "average_view_duration, average_view_percentage, subscribers_gained) FORMAT TSV",
        tsv,
    )

    print(f"video_stats_daily: {len(csv_rows)} rows")
    tsv = "\n".join(
        "\t".join(tsv_escape(x) for x in (
            r["date_utc"], r["id"], r["key"], r["thinker"], r["category"],
            r["view_count"], r["like_count"], r["comment_count"],
        ))
        for r in csv_rows
    )
    ch_exec(
        "INSERT INTO video_stats_daily (date, video_id, key, thinker, category, "
        "view_count, like_count, comment_count) FORMAT TSV",
        tsv,
    )

    rc = report["retentionCurves"]
    n_points = sum(len(v) for v in rc.values())
    print(f"retention_points: {n_points} rows ({len(rc)} videos)")
    lines = []
    for vid, points in rc.items():
        for t_ratio, watch_ratio in points:
            lines.append("\t".join(tsv_escape(x) for x in (vid, snapshot_date, t_ratio, watch_ratio)))
    ch_exec(
        "INSERT INTO retention_points (video_id, snapshot_date, t_ratio, watch_ratio) FORMAT TSV",
        "\n".join(lines),
    )

    traffic_rows = []
    for source, views in report["trafficSource28d"]:
        traffic_rows.append((snapshot_date, 28, source, views))
    for source, views in report["trafficSource7d"]:
        traffic_rows.append((snapshot_date, 7, source, views))
    print(f"traffic_source: {len(traffic_rows)} rows")
    tsv = "\n".join("\t".join(tsv_escape(x) for x in r) for r in traffic_rows)
    ch_exec("INSERT INTO traffic_source (snapshot_date, window_days, source, views) FORMAT TSV", tsv)

    subs = report["subsDaily"]
    print(f"subs_daily: {len(subs)} rows")
    tsv = "\n".join("\t".join(tsv_escape(x) for x in row) for row in subs)
    ch_exec("INSERT INTO subs_daily (date, views, subscribers_gained) FORMAT TSV", tsv)

    print("Verifying counts (FINAL, i.e. post-dedup)...")
    for table in ("videos", "video_stats_28d", "video_stats_daily", "retention_points", "traffic_source", "subs_daily"):
        count = ch_exec(f"SELECT count() FROM {table} FINAL").strip()
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
