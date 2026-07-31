"""Drive one request through the real ASGI stack, on its own thread.

Starlette's TestClient CANNOT do this: its transport collects the whole
response into a BytesIO before handing it back, so by the time a test sees a
"streamed" response the stream is long over. Anything about a response WHILE
it is in flight — above all what happens when the browser hangs up — has to be
driven at this level or it is not being tested at all.

Both streaming routes in this app depend on the same non-obvious fact:
Starlette never closes a response's body iterator itself. It relies on garbage
collection, and on the disconnect path the iterator sits in a reference cycle,
so nothing runs until the cyclic collector happens by. Cleanup therefore rides
a `BackgroundTask`. `probe` is what proves that: it is called while the event
loop is still running, so a test measures live-server behavior rather than
loop teardown (which would clean up regardless and make the test vacuous).

`spec_version: 2.3` is not decoration — Starlette picks its disconnect
handling from it, and 2.3 is what uvicorn reports.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable


class LiveRequest:
    """One in-flight ASGI request a test can hang up on.

    `probe` runs after the request ends but before the event loop closes; its
    return value lands on `probe_result`.
    """

    def __init__(
        self,
        app: Any,
        method: str,
        path: str,
        payload: dict | None = None,
        probe: Callable[[], Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.app = app
        self.method = method.upper()
        self.path = path
        self.body = b"" if payload is None else json.dumps(payload).encode()
        self.probe = probe
        self.extra_headers = headers or {}
        self.probe_result: Any = None
        self.status: int | None = None
        self.chunks: list[bytes] = []
        self._first_chunk = threading.Event()
        self._hang_up = threading.Event()
        self._finished = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        import anyio

        try:
            anyio.run(self._main)
        finally:
            self._finished.set()

    async def _main(self) -> None:
        import anyio

        request_sent = False

        async def receive():
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": self.body,
                        "more_body": False}
            # Park like a browser holding the connection open, until the test
            # hangs up.
            while not self._hang_up.is_set():
                await anyio.sleep(0.01)
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                self.status = message["status"]
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                if chunk:
                    self.chunks.append(chunk)
                    self._first_chunk.set()

        headers = [
            (b"host", b"testserver"),
            (b"content-length", str(len(self.body)).encode()),
        ]
        if self.body:
            headers.append((b"content-type", b"application/json"))
        headers += [(k.lower().encode(), v.encode())
                    for k, v in self.extra_headers.items()]

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": self.method,
            "scheme": "http",
            "path": self.path,
            "raw_path": self.path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("127.0.0.1", 50000),
            "server": ("testserver", 80),
            "state": {},
        }
        await self.app(scope, receive, send)
        # Stay alive briefly so the probe measures the live server, not the
        # cleanup that loop teardown would do anyway.
        await anyio.sleep(0.5)
        if self.probe is not None:
            self.probe_result = self.probe()

    def wait_started(self, timeout: float = 5) -> None:
        assert self._first_chunk.wait(timeout), "no response body arrived"

    def hang_up(self, timeout: float = 10) -> None:
        self._hang_up.set()
        assert self._finished.wait(timeout), "the request never finished"
