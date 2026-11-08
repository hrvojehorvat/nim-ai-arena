-- Match history: enough to replay any match from its initial configuration.

CREATE TABLE matches (
    id            text PRIMARY KEY,
    -- Game rules needed to replay: {"piles": [..], "max_take": int | null}
    config        jsonb NOT NULL,
    -- Seconds per turn; NULL = no limit. Not a rule of Nim, so kept outside `config`.
    turn_timeout  double precision,
    -- 'abandoned': the server restarted while the match was unfinished (matches live in memory).
    status        text NOT NULL CHECK (status IN ('waiting', 'active', 'finished', 'abandoned')),
    winner_id     text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);

CREATE INDEX matches_created_at_idx ON matches (created_at DESC);

CREATE TABLE match_players (
    match_id   text NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    seat       integer NOT NULL,          -- 0-based turn order
    player_id  text NOT NULL,
    name       text NOT NULL,
    kind       text NOT NULL,
    PRIMARY KEY (match_id, seat),
    UNIQUE (match_id, player_id)
);

CREATE TABLE moves (
    match_id     text NOT NULL REFERENCES matches (id) ON DELETE CASCADE,
    turn_no      integer NOT NULL,        -- 0-based index in the match's move list
    player_id    text NOT NULL,
    pile         integer NOT NULL,
    count        integer NOT NULL,
    piles_after  integer[] NOT NULL,
    auto         boolean NOT NULL DEFAULT false,  -- played by the server on turn timeout
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (match_id, turn_no)
);
