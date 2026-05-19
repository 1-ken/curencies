-- Run once against the observer Postgres database.
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS user_id VARCHAR(128);
CREATE INDEX IF NOT EXISTS ix_alerts_user_id ON alerts(user_id);
UPDATE alerts SET user_id = 'legacy-unassigned' WHERE user_id IS NULL;
ALTER TABLE alerts ALTER COLUMN user_id SET DEFAULT 'legacy-unassigned';
ALTER TABLE alerts ALTER COLUMN user_id SET NOT NULL;
