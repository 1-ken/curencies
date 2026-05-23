CREATE TABLE IF NOT EXISTS call_usage_log (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    alert_id VARCHAR(64) NOT NULL DEFAULT '',
    placed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_call_usage_log_user_placed
    ON call_usage_log (user_id, placed_at DESC);
