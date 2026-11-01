"""One-shot QR based device pairing state machine.

The QR token authorizes exactly one pending attempt. The displayed numeric
code is only a human check on the owner's trusted screen; it never grants a
session by itself.
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from dataclasses import dataclass


class PairingError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


@dataclass
class Attempt:
    identity: str
    poll_hash: str
    device: str
    peer: str
    code: str
    created: float
    expires: float
    state: str = "pending"
    bearer: str | None = None
    result_expires: float = 0.0


class PairingService:
    def __init__(self, create_session, lifetime: int = 120, clock=time.time):
        self.create_session = create_session
        self.lifetime = lifetime
        self.clock = clock
        self._lock = threading.RLock()
        self._window_id: str | None = None
        self._window_token: str | None = None
        self._window_expires = 0.0
        self._attempts: dict[str, Attempt] = {}
        self._token_used = False
        self._claims: dict[str, list[float]] = {}

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _cleanup(self, now: float) -> None:
        if self._window_id and now >= self._window_expires:
            self._window_id = self._window_token = None
            self._token_used = False
        for key, attempt in list(self._attempts.items()):
            if attempt.state == "pending" and now >= attempt.expires:
                attempt.state = "expired"
                attempt.result_expires = now + self.lifetime
            elif attempt.state != "pending" and now >= attempt.result_expires:
                self._attempts.pop(key, None)

    def window(self) -> dict:
        with self._lock:
            now = self.clock()
            self._cleanup(now)
            for attempt in self._attempts.values():
                if attempt.state == "pending":
                    return {"state": "waiting_for_owner", "attempt_id": None,
                            "token": None, "expires_in": max(0, int(attempt.expires - now))}
            if not self._window_id:
                self._window_id = secrets.token_urlsafe(18)
                self._window_token = secrets.token_urlsafe(32)
                self._window_expires = now + self.lifetime
                self._token_used = False
            return {"state": "ready", "attempt_id": self._window_id, "token": self._window_token,
                    "expires_in": max(0, int(self._window_expires - now))}

    def claim(self, attempt_id: str, token: str, poll_key: str, code: str,
              device: str, peer: str) -> dict:
        if (len(code) != 6 or not code.isascii() or not code.isdigit() or
                len(poll_key) < 40 or len(token) < 40):
            raise PairingError("Invalid pairing request", 400)
        with self._lock:
            now = self.clock()
            self._cleanup(now)
            recent = [stamp for stamp in self._claims.get(peer, []) if now - stamp < 60]
            if len(recent) >= 8:
                self._claims[peer] = recent
                raise PairingError("Too many pairing attempts; try again later", 429)
            recent.append(now)
            self._claims[peer] = recent
            if (not self._window_id or not secrets.compare_digest(attempt_id, self._window_id)
                    or not self._window_token or not secrets.compare_digest(token, self._window_token)
                    or self._token_used):
                raise PairingError("Pairing QR expired or already used", 401)
            self._token_used = True
            identity = secrets.token_urlsafe(18)
            self._attempts[identity] = Attempt(identity, self._digest(poll_key),
                device[:100], peer[:80], code, now, min(now + self.lifetime, self._window_expires))
            # Remove the bearer from the live window immediately after claim.
            self._window_id = self._window_token = None
            return {"attempt_id": identity, "expires_in": max(0, int(self._attempts[identity].expires - now))}

    def pending(self) -> list[dict]:
        with self._lock:
            self._cleanup(self.clock())
            return [{"attempt_id": a.identity, "device": a.device, "peer": a.peer,
                     "expires_in": max(0, int(a.expires - self.clock()))}
                    for a in self._attempts.values() if a.state == "pending"]

    def decide(self, identity: str, code: str, approve: bool, client_info: dict | None = None) -> dict:
        with self._lock:
            now = self.clock()
            self._cleanup(now)
            a = self._attempts.get(identity)
            if not a or a.state != "pending":
                raise PairingError("Pairing request expired or already handled", 410)
            # A mismatch is terminal, preventing repeated guessing. This code is
            # checked only after the user explicitly selects Approve.
            if approve and not secrets.compare_digest(code, a.code):
                a.state = "rejected"
                a.result_expires = now + self.lifetime
                raise PairingError("Confirmation code did not match; pairing rejected", 403)
            if approve:
                a.bearer = self.create_session()
                if client_info is not None:
                    client_info[a.bearer] = {"peer": a.peer, "agent": a.device}
                a.state = "approved"
            else:
                a.state = "rejected"
            a.result_expires = now + self.lifetime
            return {"state": a.state}

    def result(self, identity: str, poll_key: str) -> dict:
        with self._lock:
            self._cleanup(self.clock())
            a = self._attempts.get(identity)
            if not a or not secrets.compare_digest(a.poll_hash, self._digest(poll_key)):
                raise PairingError("Pairing result is unavailable", 404)
            if a.state == "approved" and a.bearer:
                token, a.bearer = a.bearer, None
                a.state = "delivered"
                return {"state": "approved", "token": token}
            return {"state": a.state}
