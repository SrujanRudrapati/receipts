# tests for the ntfy relay. a tiny local http server stands in for ntfy.sh.
import asyncio
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

import relay


def make_server(calls, poll_body=""):
    async def publish(request):
        calls.append(("POST", request.match_info["topic"], await request.text(), dict(request.query)))
        return web.json_response({"id": "x1"})

    async def poll(request):
        calls.append(("GET", request.match_info["topic"], None, dict(request.query)))
        return web.Response(text=poll_body, content_type="application/x-ndjson")

    app = web.Application()
    app.router.add_post("/{topic}", publish)
    app.router.add_get("/{topic}/json", poll)
    return TestServer(app)


def run(coro_factory, calls, poll_body=""):
    async def go():
        server = make_server(calls, poll_body)
        await server.start_server()
        try:
            async with relay.Relay(str(server.make_url("")).rstrip("/")) as r:
                return await coro_factory(r)
        finally:
            await server.close()
    return asyncio.run(go())


def test_post_sends_the_line_as_the_body():
    calls = []
    run(lambda r: r.post("receipts-abc", "receipt id=1 what=x due=none channel=c"), calls)
    assert calls == [("POST", "receipts-abc", "receipt id=1 what=x due=none channel=c", {})]


def test_poll_first_time_asks_for_the_last_ten_minutes():
    calls = []
    out = run(lambda r: r.poll("receipts-abc", since=None), calls)
    assert out == []
    assert calls == [("GET", "receipts-abc", None, {"poll": "1", "since": "10m"})]


def test_poll_passes_the_last_id_and_parses_ndjson():
    calls = []
    body = "\n".join([
        json.dumps({"id": "m1", "time": 5, "event": "message", "message": "hi"}),
        "not json at all",
        "",
        json.dumps({"id": "m2", "time": 6, "event": "keepalive"}),
    ]) + "\n"
    out = run(lambda r: r.poll("receipts-abc", since="m0"), calls, poll_body=body)
    assert calls[0][3] == {"poll": "1", "since": "m0"}
    assert [m["id"] for m in out] == ["m1", "m2"]


def test_poll_raises_on_http_error():
    async def broken(request):
        return web.Response(status=500)

    async def go():
        app = web.Application()
        app.router.add_get("/{topic}/json", broken)
        server = TestServer(app)
        await server.start_server()
        try:
            async with relay.Relay(str(server.make_url("")).rstrip("/")) as r:
                with pytest.raises(Exception):
                    await r.poll("receipts-abc", since=None)
        finally:
            await server.close()
    asyncio.run(go())


def test_default_base_is_ntfy_sh():
    assert relay.DEFAULT_BASE == "https://ntfy.sh"
