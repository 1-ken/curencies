CREATE TABLE IF NOT EXISTS ohlc_candles (
    id SERIAL PRIMARY KEY,
    pair VARCHAR(64) NOT NULL,
    interval VARCHAR(8) NOT NULL,
    bucket_time TIMESTAMPTZ NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT uq_ohlc_candles_pair_interval_bucket UNIQUE (pair, interval, bucket_time)
);

CREATE INDEX IF NOT EXISTS ix_ohlc_candles_pair ON ohlc_candles (pair);
CREATE INDEX IF NOT EXISTS ix_ohlc_candles_interval ON ohlc_candles (interval);
CREATE INDEX IF NOT EXISTS ix_ohlc_candles_bucket_time ON ohlc_candles (bucket_time);
