"""Redis integration for caching and pub/sub streaming."""
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
    ) -> None:
        self.url = url
        self.channel = channel
        self.latest_key = latest_key
        self.queue_key = queue_key
        self.recent_key = recent_key
        self.recent_maxlen = recent_maxlen
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        self._client = redis.Redis.from_url(self.url, decode_responses=True)
        await self._client.ping()
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

    async def publish_snapshot(self, data: Dict[str, Any]) -> None:
        payload = json.dumps(data)
        await self.client.set(self.latest_key, payload)
        await self.client.publish(self.channel, payload)
        await self.client.rpush(self.queue_key, payload)
        await self.client.lpush(self.recent_key, payload)
        await self.client.ltrim(self.recent_key, 0, max(self.recent_maxlen - 1, 0))

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

    async def subscribe(self) -> AsyncIterator[Dict[str, Any]]:
        pubsub = self.client.pubsub()
        await pubsub.subscribe(self.channel)
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if not message:
                    continue
                if message.get("type") != "message":
                    continue
                data = json.loads(message.get("data", "{}"))
                yield data
        finally:
            await pubsub.unsubscribe(self.channel)
            await pubsub.close()
