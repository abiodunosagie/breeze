"""The helper's gate: only this app, with its launch token, gets in."""

import asyncio

from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

import server


def make_app(token="secret"):
    app = web.Application(middlewares=[server.local_only])
    app[server.SESSION] = server.Session()
    app[server.TOKEN] = token
    app.router.add_get("/health", server.health)
    return app


def check(headers, host_ok=True):
    async def run():
        app = make_app()
        async with TestClient(TestServer(app)) as client:
            port = client.server.port
            app[server.ALLOWED_HOSTS] = frozenset({f"127.0.0.1:{port}"} if host_ok else {"elsewhere:1"})
            app[server.ALLOWED_ORIGINS] = frozenset({f"http://127.0.0.1:{port}"})
            response = await client.get("/health", headers=headers)
            return response.status
    return asyncio.run(run())


def test_token_is_required():
    assert check({}) == 403
    assert check({"X-Breeze-Token": "wrong"}) == 403
    assert check({"X-Breeze-Token": "secret"}) == 200


def test_foreign_host_and_origin_are_refused():
    assert check({"X-Breeze-Token": "secret"}, host_ok=False) == 403
    assert check({"X-Breeze-Token": "secret", "Origin": "https://evil.example"}) == 403


def test_unknown_requests_get_a_plain_error():
    sent = []

    class Socket:
        async def send_json(self, message):
            sent.append(message)

    async def run():
        session = server.Session()
        await server.handle_message(session, Socket(), "not json")
        await server.handle_message(session, Socket(), '{"type": "rm -rf"}')
        await server.handle_message(session, Socket(), '{"type": "ac_set", "changes": {"power": true}}')
    asyncio.run(run())
    assert [m["message"] for m in sent][:2] == ["Bad message.", "Bad message."]
    assert sent[2]["message"] == "The air conditioner is not reachable right now."
