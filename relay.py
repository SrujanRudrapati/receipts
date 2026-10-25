# the network side of the cubbie link. talks to ntfy over plain http with aiohttp.
# nothing here logs. errors go up to the caller, which logs the error type only,
# because an aiohttp error message can carry the url, and the url is the topic.
import json

import aiohttp

DEFAULT_BASE = "https://ntfy.sh"
FIRST_POLL_SINCE = "10m"
TIMEOUT_SECONDS = 10


class Relay:
    def __init__(self, base: str = DEFAULT_BASE):
        self.base = base
        self._session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "Relay":
        await self.open()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def open(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _url(self, topic: str, suffix: str = "") -> str:
        return f"{self.base}/{topic}{suffix}"

    async def post(self, topic: str, line: str) -> None:
        await self.open()
        async with self._session.post(self._url(topic), data=line.encode()) as response:
            response.raise_for_status()

    async def poll(self, topic: str, since: str | None) -> list[dict]:
        """messages on the topic after `since`, oldest first. one dict per ntfy json line."""
        await self.open()
        params = {"poll": "1", "since": since or FIRST_POLL_SINCE}
        async with self._session.get(self._url(topic, "/json"), params=params) as response:
            response.raise_for_status()
            body = await response.text()
        return _parse_ndjson(body)


def _parse_ndjson(body: str) -> list[dict]:
    out = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out
