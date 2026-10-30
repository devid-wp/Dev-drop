"""Process-local PC -> browser offers backed by private disk snapshots."""
import hashlib
import hmac
import os
import secrets
import shutil
import stat
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from app.uploads import safe_upload_name


class OfferError(ValueError):
    pass


@dataclass
class FileOffer:
    id: str
    recipient: str  # Actual session credential; never included in public data.
    recipient_id: str
    filename: str
    size: int
    created_at: float
    expires_at: float
    snapshot: Path
    status: str = "pending"
    grant_hash: str | None = None
    sender: str = "Computer owner"
    expire_stream: bool = False
    sent_bytes: int = 0
    stream_started_at: float | None = None
    stream_finished_at: float | None = None

    def public(self):
        return {"id": self.id, "recipient_id": self.recipient_id,
                "filename": self.filename, "size": self.size, "sender": self.sender,
                "created_at": self.created_at, "expires_at": self.expires_at, "status": self.status,
                "sent_bytes": self.sent_bytes, "stream_started_at": self.stream_started_at,
                "stream_finished_at": self.stream_finished_at}


class FileOfferService:
    def __init__(self, lifetime=300, clock=time.time, directory=None):
        self.lifetime, self.clock = lifetime, clock
        self._directory = directory
        self._temporary = None
        self._lock = threading.RLock()
        self._offers = {}
        self._preparing = 0

    def _root(self):
        if self._directory is None:
            self._temporary = tempfile.TemporaryDirectory(prefix="devdrop-outgoing-")
            self._directory = Path(self._temporary.name)
        self._directory.mkdir(parents=True, exist_ok=True)
        return self._directory

    def _remove(self, offer):
        try:
            offer.snapshot.unlink(missing_ok=True)
        except OSError:
            pass  # Retry on the next sweep (e.g. a Windows file still closing).

    def _sweep(self):
        now = self.clock()
        for offer in list(self._offers.values()):
            if offer.expires_at <= now and (offer.status in {"preparing", "pending", "accepted"} or (offer.status == "streaming" and offer.expire_stream)):
                offer.status, offer.grant_hash = "expired", None
            if offer.status not in {"preparing", "pending", "accepted", "streaming"}:
                self._remove(offer)
                if now > offer.expires_at + 3600 and not offer.snapshot.exists():
                    self._offers.pop(offer.id, None)

    def create(self, source: Path, recipient: str, recipient_id: str):
        try:
            if source.is_symlink() or not stat.S_ISREG(source.stat().st_mode):
                raise OfferError("Choose a regular readable file, not a symbolic link")
            flags = getattr(os, "O_NONBLOCK", 0) | os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(source, flags), "rb") as incoming:
                before = os.fstat(incoming.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise OfferError("Choose a regular readable file")
                def validate():
                    after = os.fstat(incoming.fileno())
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise OfferError("File changed while preparing the offer; try again")
                return self.create_stream(incoming, source.name, recipient, recipient_id, validate=validate)
        except OSError as error:
            raise OfferError("File is missing or unavailable") from error

    def create_stream(self, incoming, filename, recipient, recipient_id, *, validate=None,
                      deadline=None, sender="Computer owner", published=True):
        """Copy a server-owned stream; no remote request can choose its path."""
        with self._lock:
            self._sweep()
            if len(self._offers) + self._preparing >= 100:
                raise OfferError("Too many file offers")
            try:
                root = self._root()
            except OSError as error:
                raise OfferError("Cannot prepare private file storage") from error
            self._preparing += 1
        snapshot = None
        try:
            with tempfile.NamedTemporaryFile(dir=root, delete=False) as output:
                snapshot = Path(output.name)
                shutil.copyfileobj(incoming, output, length=256 * 1024)
            if validate is not None:
                validate()
            with self._lock:
                now = self.clock()
                expires = min(now + self.lifetime, deadline) if deadline is not None else now + self.lifetime
                if expires <= now:
                    raise OfferError("File offer expired during preparation")
                offer = FileOffer(secrets.token_urlsafe(24), recipient, recipient_id,
                                  safe_upload_name(filename), snapshot.stat().st_size,
                                  now, expires, snapshot, status="pending" if published else "preparing",
                                  sender=sender, expire_stream=deadline is not None)
                self._offers[offer.id] = offer
                snapshot = None
                return offer.public()
        except OSError as error:
            raise OfferError("Cannot prepare the offered file") from error
        finally:
            with self._lock:
                self._preparing -= 1
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)

    def publish(self, identity):
        with self._lock:
            offer = self._get(identity)
            if offer.status != "preparing":
                raise OfferError("File offer is unavailable")
            offer.status = "pending"

    def discard_prepared(self, identity):
        with self._lock:
            offer = self._get(identity)
            if offer.status not in {"preparing", "expired", "cancelled"}:
                raise OfferError("Published file offer cannot be discarded")
            self._remove(offer)
            self._offers.pop(identity, None)

    def state(self, identity):
        with self._lock:
            return self._get(identity).public()

    def check_streaming(self, identity):
        with self._lock:
            if self._get(identity).status != "streaming":
                raise OfferError("Download was cancelled or expired")

    def record_stream_bytes(self, identity, amount):
        """Count server-yielded bytes; this does not prove browser persistence."""
        with self._lock:
            offer = self._get(identity)
            if offer.status != "streaming":
                raise OfferError("Download was cancelled or expired")
            offer.sent_bytes = min(offer.size, offer.sent_bytes + amount)

    def _get(self, identity, recipient=None):
        self._sweep()
        offer = self._offers.get(identity)
        if offer is None or (recipient is not None and offer.recipient != recipient):
            raise OfferError("File offer is unavailable")
        return offer

    def list(self, recipient=None):
        with self._lock:
            self._sweep()
            return [offer.public() for offer in self._offers.values()
                    if offer.status != "preparing" and (recipient is None or offer.recipient == recipient)]

    def accept(self, identity, recipient):
        with self._lock:
            offer = self._get(identity, recipient)
            if offer.status != "pending":
                raise OfferError("File offer is no longer pending")
            grant = secrets.token_urlsafe(32)
            offer.status = "accepted"
            offer.grant_hash = hashlib.sha256(grant.encode()).hexdigest()
            return offer.public(), grant

    def reject(self, identity, recipient):
        with self._lock:
            offer = self._get(identity, recipient)
            if offer.status != "pending":
                raise OfferError("File offer is no longer pending")
            offer.status = "rejected"
            self._remove(offer)
            return offer.public()

    def cancel(self, identity):
        with self._lock:
            offer = self._get(identity)
            if offer.status not in {"preparing", "pending", "accepted"} and not (offer.status == "streaming" and offer.expire_stream):
                raise OfferError("File offer cannot be cancelled")
            offer.status, offer.grant_hash = "cancelled", None
            self._remove(offer)
            return offer.public()

    def claim(self, identity, grant, session_valid, recipient=None):
        with self._lock:
            offer = self._get(identity, recipient)
            if (offer.status != "accepted" or not grant or not offer.grant_hash or
                not hmac.compare_digest(offer.grant_hash, hashlib.sha256(grant.encode()).hexdigest()) or
                not session_valid(offer.recipient)):
                raise OfferError("Download is not authorized or was already used")
            try:
                source = offer.snapshot.open("rb")
            except OSError as error:
                offer.status, offer.grant_hash = "failed", None
                raise OfferError("Offered file is unavailable") from error
            offer.status, offer.grant_hash = "streaming", None
            offer.sent_bytes = 0
            offer.stream_started_at = self.clock()
            offer.stream_finished_at = None
            return offer.public(), source

    def finish(self, identity, succeeded):
        with self._lock:
            offer = self._offers.get(identity)
            if offer is not None:
                if offer.status == "streaming":
                    offer.status = "sent" if succeeded else "failed"
                    offer.stream_finished_at = self.clock()
                self._remove(offer)

    def close(self):
        with self._lock:
            for offer in self._offers.values():
                self._remove(offer)
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None
                self._directory = None
            self._offers.clear()
