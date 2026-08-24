-- clickcuts-db schema (Agentic Cinema hackathon, ClickHouse track)
-- Normalized so retention curves support range queries, not one Array() blob.

-- structure = A/interpretation | B/? | C/counterpoint narrative-card variant (CLAUDE.md §9.13,
-- introduced 2026-07-26). '' = pre-variant video or non-QA content (e.g. longform sleep pilots,
-- thinker='mixed') — the agent must exclude '' rows from structure comparisons, not treat as a 4th bucket.
CREATE TABLE IF NOT EXISTS videos (
    video_id        String,
    key             String,
    thinker         String,
    category        String,
    title           String,
    structure       String DEFAULT '',
    structure_name  String DEFAULT ''
) ENGINE = ReplacingMergeTree
ORDER BY video_id;

-- 28-day rollup snapshot per video (from YouTube Analytics API pull)
CREATE TABLE IF NOT EXISTS video_stats_28d (
    video_id                    String,
    snapshot_date                Date,
    views                        UInt32,
    estimated_minutes_watched    UInt32,
    average_view_duration        Float64,
    average_view_percentage      Float64,
    subscribers_gained           Int32
) ENGINE = ReplacingMergeTree
ORDER BY (video_id, snapshot_date);

-- Daily view/engagement time series per video (from views_log.csv)
CREATE TABLE IF NOT EXISTS video_stats_daily (
    date            Date,
    video_id        String,
    key             String,
    thinker         String,
    category        String,
    view_count      UInt32,
    like_count      UInt32,
    comment_count   UInt32
) ENGINE = ReplacingMergeTree
ORDER BY (video_id, date);

-- Normalized retention curve: one row per (video, time-ratio) point.
-- Enables range queries like "where does watch_ratio drop fastest" per segment.
CREATE TABLE IF NOT EXISTS retention_points (
    video_id      String,
    snapshot_date Date,
    t_ratio       Float64,
    watch_ratio   Float64
) ENGINE = ReplacingMergeTree
ORDER BY (video_id, t_ratio);

-- Traffic source breakdown per window (28d/7d snapshots)
CREATE TABLE IF NOT EXISTS traffic_source (
    snapshot_date   Date,
    window_days     UInt16,
    source          String,
    views           UInt32
) ENGINE = ReplacingMergeTree
ORDER BY (snapshot_date, window_days, source);

-- Daily channel-wide views + subscriber gain (source metrics: views,subscribersGained)
CREATE TABLE IF NOT EXISTS subs_daily (
    date                Date,
    views               UInt32,
    subscribers_gained  Int32
) ENGINE = ReplacingMergeTree
ORDER BY date;
