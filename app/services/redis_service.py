"""Redis integration for caching and pub/sub streaming."""
import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisService:
    def __init__(
        self,
        url: str,
        channel: str,
        latest_key: str,
        queue_key: str,
        recent_key: str,
        recent_maxlen: int,
        socket_connect_timeout_seconds: float = 2.0,
        socket_timeout_seconds: float = 2.0,
        retry_max_attempts: int = 5,
        retry_base_delay_seconds: float = 0.5,
        retry_max_delay_seconds: float = 5.0,
    ) -> None:
        self.url = url
        self.channel = channel
        self.latest_key = latest_key
        self.queue_key = queue_key
        self.recent_key = recent_key
        self.recent_maxlen = recent_maxlen
        self.socket_connect_timeout_seconds = max(0.1, float(socket_connect_timeout_seconds))
        self.socket_timeout_seconds = max(0.1, float(socket_timeout_seconds))
        self.retry_max_attempts = max(1, int(retry_max_attempts))
        self.retry_base_delay_seconds = max(0.05, float(retry_base_delay_seconds))
        self.retry_max_delay_seconds = max(
            self.retry_base_delay_seconds,
            float(retry_max_delay_seconds),
        )
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        self._client = redis.Redis.from_url(
            self.url,
            decode_responses=True,
            socket_connect_timeout=self.socket_connect_timeout_seconds,
            socket_timeout=self.socket_timeout_seconds,
            retry_on_timeout=True,
            health_check_interval=30,
        )
        await self._run_with_retry("connect_ping", self._client.ping)
        logger.info("Redis connected: %s", self.url)

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis connection closed")

    @property
    def client(self) -> redis.Redis:
        if not self._client:
            raise RuntimeError("Redis client not initialized")
        return self._client

    async def _run_with_retry(self, action: str, fn):
        delay = self.retry_base_delay_seconds
        last_error: Optional[Exception] = None

        for attempt in range(1, self.retry_max_attempts + 1):
            try:
                return await fn()
            except (redis.ConnectionError, redis.TimeoutError) as e:
                last_error = e
                if attempt >= self.retry_max_attempts:
                    break
                logger.warning(
                    "Redis %s failed (%s/%s): %s; retrying in %.2fs",
                    action,
                    attempt,
                    self.retry_max_attempts,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.retry_max_delay_seconds)

        if last_error:
            raise last_error

        raise RuntimeError(f"Redis {action} failed without specific error")

    async def publish_snapshot(self, data: Dict[str, Any]) -> None:
        payload = json.dumps(data)

        async def _publish() -> None:
            await self.client.set(self.latest_key, payload)
            await self.client.publish(self.channel, payload)
            await self.client.rpush(self.queue_key, payload)
            await self.client.lpush(self.recent_key, payload)
            await self.client.ltrim(self.recent_key, 0, max(self.recent_maxlen - 1, 0))

        await self._run_with_retry("publish_snapshot", _publish)

    async def get_latest(self) -> Optional[Dict[str, Any]]:
        payload = await self.client.get(self.latest_key)
        if not payload:
            return None
        return json.loads(payload)

    async def get_recent(self, count: int = 50) -> List[Dict[str, Any]]:
        payloads = await self.client.lrange(self.recent_key, 0, max(count - 1, 0))
        return [json.loads(item) for item in payloads]

    async def read_queue(self, batch_size: int) -> List[Dict[str, Any]]:
        payloads = await self.client.lpop(self.queue_key, count=batch_size)
        if not payloads:
            return []
        if isinstance(payloads, str):
            payloads = [payloads]
        return [json.loads(item) for item in payloads]

    async def subscribe(self, stop_event: Optional[asyncio.Event] = None) -> AsyncIterator[Dict[str, Any]]:
        reconnect_attempt = 0

        while True:
            if stop_event and stop_event.is_set():
                break

            pubsub = self.client.pubsub()
            try:
                await self._run_with_retry("subscribe", lambda: pubsub.subscribe(self.channel))
                reconnect_attempt = 0

                while True:
                    if stop_event and stop_event.is_set():
                        return

                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    if not message:
                        continue
                    if message.get("type") != "message":
                        continue
                    data = json.loads(message.get("data", "{}"))
                    yield data
            except (redis.ConnectionError, redis.TimeoutError) as e:
                reconnect_attempt += 1
                if reconnect_attempt >= self.retry_max_attempts:
                    logger.error(
                        "Redis subscribe failed after %s attempts: %s",
                        reconnect_attempt,
                        e,
                    )
                    raise

                delay = min(
                    self.retry_base_delay_seconds * (2 ** (reconnect_attempt - 1)),
                    self.retry_max_delay_seconds,
                )
                logger.warning(
                    "Redis subscribe error (%s/%s): %s; reconnecting in %.2fs",
                    reconnect_attempt,
                    self.retry_max_attempts,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)
            finally:
                try:
                    await pubsub.unsubscribe(self.channel)
                except Exception:
                    pass
                try:
                    await pubsub.close()
                except Exception:
                    pass
