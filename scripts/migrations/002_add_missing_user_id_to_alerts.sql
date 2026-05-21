-- Backfill old databases whose alerts table was created before user_id existed.
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS user_id VARCHAR(128);
UPDATE alerts SET user_id = 'legacy-unassigned' WHERE user_id IS NULL;
ALTER TABLE alerts ALTER COLUMN user_id SET DEFAULT 'legacy-unassigned';
ALTER TABLE alerts ALTER COLUMN user_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_alerts_user_id ON alerts(user_id);