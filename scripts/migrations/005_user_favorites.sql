CREATE TABLE IF NOT EXISTS user_favorites (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(128) NOT NULL,
    pair VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_favorites_user_pair UNIQUE (user_id, pair)
);

CREATE INDEX IF NOT EXISTS ix_user_favorites_user_id ON user_favorites (user_id);
CREATE INDEX IF NOT EXISTS ix_user_favorites_pair ON user_favorites (pair);
