-- Badminton CV data model (DuckDB). Superset of ShuttleSet.
-- Tier 1: strokes (tactical truth). Tier 2: tracks + shuttle (per-frame, our extension).
-- Run:  duckdb badminton.db < schema/schema.sql

-- shot_type (ShuttleSet22 canonical, 10 classes): short service, long service, clear,
-- drive, drop, lob, net shot, smash, push/rush, defensive shot.
-- (Original KDD ShuttleSet had 18 finer classes; ShuttleSet22 collapses them to 10.)
--
-- Coordinates: pipeline rows are court METRES (coord_space='court_m'); ShuttleSet
-- imports are raw broadcast PIXELS (coord_space='pixel') — no homography is shipped,
-- so they're converted to metres later using the match's calibrated homography.
-- Each stroke has THREE spatial points: hitter feet (hitter_*), shuttle contact
-- (hit_*), shuttle landing (landing_*); plus opponent feet (receiver_*).

CREATE TABLE IF NOT EXISTS matches (
    match_id      VARCHAR PRIMARY KEY,
    discipline    VARCHAR,                 -- 'singles' | 'doubles'
    player_near   VARCHAR,                 -- neutral IDs (court half), NOT winner/loser
    player_far    VARCHAR,
    tournament    VARCHAR,
    match_date    DATE,
    video_id      VARCHAR,                 -- source video (e.g. YouTube id) if available
    video_url     VARCHAR,
    fps           DOUBLE,                  -- needed: frame_num = seconds * fps
    width         INTEGER,
    height        INTEGER,
    camera_view   VARCHAR,                 -- 'broadcast' | 'controlled'
    homography    DOUBLE[9],               -- 3x3 row-major, image px -> court metres
    source        VARCHAR DEFAULT 'pipeline'  -- 'shuttleset' | 'pipeline'
);

-- TIER 1 ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS strokes (
    stroke_id          BIGINT PRIMARY KEY,
    match_id           VARCHAR REFERENCES matches(match_id),
    set_no             INTEGER,            -- 1..3
    rally_id           INTEGER,            -- ShuttleSet `rally`
    ball_round         INTEGER,            -- stroke index within rally
    time               VARCHAR,            -- hh:mm:ss
    frame_num          BIGINT,             -- contact frame
    roundscore_near    INTEGER,
    roundscore_far     INTEGER,
    -- Player IDs: 'near'|'far' for pipeline rows; raw 'A'|'B' for shuttleset imports
    -- (A=match winner) until resolve_near_far() relabels them via the homography.
    hitter             VARCHAR,
    receiver           VARCHAR,
    server             VARCHAR,            -- ShuttleSet `server`
    shot_type          VARCHAR,            -- canonical English (10 classes); NULL if unknown
    shot_type_raw      VARCHAR,            -- original ShuttleSet label (e.g. Chinese)
    aroundhead         BOOLEAN,
    backhand           BOOLEAN,
    coord_space        VARCHAR DEFAULT 'court_m',   -- 'court_m' | 'pixel'

    -- spatial: feet of hitter/receiver, shuttle contact (hit_*), shuttle landing.
    -- units per coord_space; *_area = ShuttleSet grid zone; *_height = above/below net code.
    hitter_x           DOUBLE, hitter_y   DOUBLE, hitter_area   INTEGER,
    receiver_x         DOUBLE, receiver_y DOUBLE, receiver_area INTEGER,
    hit_x              DOUBLE, hit_y      DOUBLE, hit_area       INTEGER, hit_height     DOUBLE,
    landing_x          DOUBLE, landing_y  DOUBLE, landing_area   INTEGER, landing_height DOUBLE,

    -- rally outcome (populated on last stroke)
    lose_reason        VARCHAR,
    win_reason         VARCHAR,
    getpoint_player    VARCHAR,            -- 'near'|'far' (or raw 'A'|'B' for imports)
    flaw               VARCHAR,
    db                 INTEGER,            -- ShuttleSet dead-bird / end flag

    -- OUR derived/extracted extras (NULL for shuttleset-imported rows)
    shuttle_speed_kmh   DOUBLE,
    contact_height_m    DOUBLE,
    hitter_dist_moved_m DOUBLE,            -- since hitter's previous stroke
    recovery_error_m    DOUBLE,            -- gap from center base at opponent's contact
    rally_shot_count    INTEGER,
    is_error            BOOLEAN,
    error_type          VARCHAR,           -- 'forced' | 'unforced' | NULL

    -- provenance / confidence
    shot_type_conf     DOUBLE,
    landing_conf       DOUBLE,
    source             VARCHAR DEFAULT 'pipeline'
);

-- TIER 2 ------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tracks (
    match_id    VARCHAR REFERENCES matches(match_id),
    frame_num   BIGINT,
    player_id   VARCHAR,                   -- 'near' | 'far' (+ doubles: 'near2'/'far2')
    court_x     DOUBLE, court_y DOUBLE,    -- feet on floor plane, court metres
    img_x       DOUBLE, img_y   DOUBLE,    -- pixel feet point
    bbox        DOUBLE[4],                 -- x,y,w,h pixels
    keypoints   DOUBLE[51],                -- 17 COCO keypoints * (x,y,conf)
    pose_conf   DOUBLE,
    PRIMARY KEY (match_id, frame_num, player_id)
);

CREATE TABLE IF NOT EXISTS shuttle (
    match_id     VARCHAR REFERENCES matches(match_id),
    frame_num    BIGINT,
    img_x        DOUBLE, img_y DOUBLE,     -- screen-space (2D)
    court_x      DOUBLE, court_y DOUBLE,   -- only valid at landing (on floor plane)
    visible      BOOLEAN,                  -- detected vs occluded
    interpolated BOOLEAN,                  -- Kalman-filled gap
    conf         DOUBLE,
    PRIMARY KEY (match_id, frame_num)
);

-- Indexes for the common access patterns
CREATE INDEX IF NOT EXISTS idx_strokes_rally ON strokes(match_id, set_no, rally_id, ball_round);
CREATE INDEX IF NOT EXISTS idx_tracks_match  ON tracks(match_id, frame_num);
