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

    def public(self):
        return {"id": self.id, "recipient_id": self.recipient_id,
                "filename": self.filename, "size": self.size, "sender": "Computer owner",
                "created_at": self.created_at, "expires_at": self.expires_at, "status": self.status}


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
            if offer.expires_at <= now and offer.status in {"pending", "accepted"}:
                offer.status, offer.grant_hash = "expired", None
            if offer.status not in {"pending", "accepted", "streaming"}:
                self._remove(offer)
                if now > offer.expires_at + 3600 and not offer.snapshot.exists():
                    self._offers.pop(offer.id, None)

    def create(self, source: Path, recipient: str, recipient_id: str):
        # Reserve a bounded slot; disk copying must not hold the state lock.
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
            if source.is_symlink():
                raise OfferError("Choose a regular file, not a symbolic link")
            if not stat.S_ISREG(source.stat().st_mode):
                raise OfferError("Choose a regular readable file")
            flags = getattr(os, "O_NONBLOCK", 0) | os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(source, flags), "rb") as incoming:
                if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode):
                    raise OfferError("Choose a regular readable file")
                before = os.fstat(incoming.fileno())
                with tempfile.NamedTemporaryFile(dir=root, delete=False) as output:
                    snapshot = Path(output.name)
                    shutil.copyfileobj(incoming, output, length=256 * 1024)
                after = os.fstat(incoming.fileno())
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise OfferError("File changed while preparing the offer; try again")
            with self._lock:
                now = self.clock()
                offer = FileOffer(secrets.token_urlsafe(24), recipient, recipient_id,
                                  safe_upload_name(source.name), snapshot.stat().st_size,
                                  now, now + self.lifetime, snapshot)
                self._offers[offer.id] = offer
                snapshot = None
                return offer.public()
        except OSError as error:
            raise OfferError("File is missing or unavailable") from error
        finally:
            with self._lock:
                self._preparing -= 1
            if snapshot is not None:
                snapshot.unlink(missing_ok=True)

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
                    if recipient is None or offer.recipient == recipient]

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
            if offer.status not in {"pending", "accepted"}:
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
            return offer.public(), source

    def finish(self, identity, succeeded):
        with self._lock:
            offer = self._offers.get(identity)
            if offer is not None:
                if offer.status == "streaming":
                    offer.status = "sent" if succeeded else "failed"
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
