CREATE TABLE IF NOT EXISTS user_activity_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(128),
    event_type VARCHAR(64) NOT NULL,
    ip_address VARCHAR(64),
    user_agent VARCHAR(512),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_user_activity_log_user_id ON user_activity_log (user_id);
CREATE INDEX IF NOT EXISTS ix_user_activity_log_event_type ON user_activity_log (event_type);
CREATE INDEX IF NOT EXISTS ix_user_activity_log_created_at ON user_activity_log (created_at DESC);
