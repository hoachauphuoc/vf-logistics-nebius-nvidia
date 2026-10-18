"""
The conformance check for a system that receives Floorline's decisions (N01): it is run
against the receiver's own endpoint and says, per obligation of the contract, PASS, FAIL or
UNVERIFIED. Tested against small local receivers that do and do not meet the contract.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import receiver_conformance as rc  # noqa: E402


class Receiver:
    """A local receiver. idempotent: a repeat is only counted. require_key: no key, no apply."""

    def __init__(self, *, idempotent: bool, require_key: bool = True):
        self.idempotent, self.require_key = idempotent, require_key
        self.applied: dict[str, int] = {}
        self.lock = threading.Lock()
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body):
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                message = json.loads(self.rfile.read(length) or b"{}").get("message") or {}
                key = (message.get("attributes") or {}).get("idempotency_key") or ""
                if not key and receiver.require_key:
                    return self._send(422, {"outcome": "rejected"})
                key = key or "no-key"
                with receiver.lock:
                    if receiver.idempotent:
                        receiver.applied.setdefault(key, 1)
                    else:
                        receiver.applied[key] = receiver.applied.get(key, 0) + 1
                self._send(200, {"outcome": "ok"})

            def do_GET(self):
                key = self.path.rsplit("/", 1)[-1]
                with receiver.lock:
                    count = receiver.applied.get(key)
                if count is None:
                    return self._send(404, {"error": "unknown key"})
                self._send(200, {"result": {"applied": count}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def serve():
    started: list[Receiver] = []

    def start(**kwargs) -> Receiver:
        started.append(Receiver(**kwargs))
        return started[-1]

    yield start
    for receiver in started:
        receiver.close()


def results(rows):
    return {name: result for name, result, _ in rows}


class TestAReceiverThatMeetsTheContract:
    def test_every_obligation_passes_and_the_exit_code_is_zero(self, serve):
        receiver = serve(idempotent=True)
        rows = rc.check(receiver.url + "/push", applied_url=receiver.url + "/applied/{key}", count_field="result.applied")
        assert {r for r in results(rows).values()} == {"PASS"}
        assert rc.exit_code(rows) == 0

    def test_without_a_way_to_read_the_count_the_last_obligation_is_unverified(self, serve):
        receiver = serve(idempotent=True)
        rows = rc.check(receiver.url + "/push")
        verdict = results(rows)
        assert verdict["applied once"] == "UNVERIFIED"
        assert [v for k, v in verdict.items() if k != "applied once"] == ["PASS"] * (len(verdict) - 1)
        assert rc.exit_code(rows) == 2


class TestAReceiverThatBreaksIt:
    def test_a_receiver_that_applies_every_delivery_fails_applied_once(self, serve):
        receiver = serve(idempotent=False)
        rows = rc.check(receiver.url + "/push", applied_url=receiver.url + "/applied/{key}", count_field="result.applied")
        verdict = results(rows)
        assert verdict["applied once"] == "FAIL"
        assert "applied" in dict((n, d) for n, _, d in rows)["applied once"]
        assert rc.exit_code(rows) == 1

    def test_a_receiver_that_accepts_a_message_without_a_key_fails(self, serve):
        receiver = serve(idempotent=True, require_key=False)
        rows = rc.check(receiver.url + "/push", applied_url=receiver.url + "/applied/{key}", count_field="result.applied")
        assert results(rows)["refuses a message without an idempotency_key"] == "FAIL"
        assert rc.exit_code(rows) == 1

    def test_a_closed_port_fails_every_delivery_check_without_raising(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        rows = rc.check(f"http://127.0.0.1:{port}/push", timeout=2)
        assert results(rows)["acknowledges a first delivery"] == "FAIL"
        assert rc.exit_code(rows) == 1


class TestARefusalForTheWrongReason:
    def test_a_receiver_that_refuses_everything_for_lack_of_a_token_does_not_pass_the_keyless_check(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                self.send_response(401)
                self.send_header("Content-Length", "0")
                self.end_headers()

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            rows = rc.check(f"http://127.0.0.1:{server.server_address[1]}/push")
        finally:
            server.shutdown()
            server.server_close()
        verdict = results(rows)
        assert verdict["acknowledges a first delivery"] == "FAIL"
        assert verdict["refuses a message without an idempotency_key"] == "FAIL"
        assert rc.exit_code(rows) == 1


class TestTheCommandLine:
    def test_main_prints_a_verdict_per_check_and_returns_the_exit_code(self, serve, capsys):
        receiver = serve(idempotent=True)
        code = rc.main([receiver.url + "/push", "--applied-url", receiver.url + "/applied/{key}", "--count-field", "result.applied"])
        out = capsys.readouterr().out
        assert code == 0
        assert "[PASS] acknowledges a first delivery" in out
        assert "[PASS] applied once" in out
