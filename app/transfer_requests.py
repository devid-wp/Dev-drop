"""Process-local, session-bound, one-use transfer approvals."""
import secrets
import threading
import time
from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class FileDescription(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class TransferDescription(BaseModel):
    type: Literal["file", "text", "link"]
    sender: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    size: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    files: list[FileDescription] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_content(self):
        if self.type == "file":
            if not self.files or self.sha256 is not None:
                raise ValueError("File transfers require a file manifest")
            total = sum(file.size for file in self.files)
            if self.size is not None and self.size != total:
                raise ValueError("Size does not match manifest")
            self.size = total
        elif self.files or self.sha256 is None:
            raise ValueError("Text and links require a content digest")
        return self


class TransferError(ValueError):
    pass


@dataclass
class TransferRequest:
    id: str
    session: str
    content: dict
    created_at: float
    expires_at: float
    status: Literal["pending", "approved", "rejected", "expired", "cancelled"] = "pending"
    used: bool = False

    def public(self):
        result = asdict(self)
        result.pop("session")
        result.update(result.pop("content"))
        return result


class TransferService:
    def __init__(self, lifetime=120, clock=time.time):
        self.lifetime = lifetime
        self.clock = clock
        self._lock = threading.Lock()
        self._requests = {}

    def _expire(self):
        now = self.clock()
        for item in self._requests.values():
            if item.expires_at <= now and item.status in {"pending", "approved"} and not item.used:
                item.status = "expired"
        self._requests = {key: item for key, item in self._requests.items()
                          if item.expires_at + 3600 > now}

    def create(self, session, description: TransferDescription):
        with self._lock:
            self._expire()
            active = [r for r in self._requests.values() if r.session == session
                      and r.status in {"pending", "approved"} and not r.used]
            if len(active) >= 20 or len(self._requests) >= 1000:
                raise TransferError("Too many transfer requests")
            now = self.clock()
            item = TransferRequest(secrets.token_urlsafe(24), session,
                                   description.model_dump(), now, now + self.lifetime)
            self._requests[item.id] = item
            return item.public()

    def _get(self, identity, session=None):
        self._expire()
        item = self._requests.get(identity)
        if item is None or (session is not None and item.session != session):
            raise TransferError("Transfer request not available")
        return item

    def state(self, identity, session):
        with self._lock:
            return self._get(identity, session).public()

    def pending(self):
        with self._lock:
            self._expire()
            return [r.public() for r in self._requests.values() if r.status == "pending"]

    def decide(self, identity, approve):
        with self._lock:
            item = self._get(identity)
            if item.status != "pending":
                raise TransferError("Transfer request is no longer pending")
            item.status = "approved" if approve else "rejected"
            return item.public()

    def cancel(self, identity, session):
        with self._lock:
            item = self._get(identity, session)
            if item.used or item.status not in {"pending", "approved"}:
                raise TransferError("Transfer request cannot be cancelled")
            item.status = "cancelled"
            return item.public()

    def check_approved(self, identity, session):
        with self._lock:
            item = self._get(identity, session)
            if item.status != "approved" or item.used:
                raise TransferError("Transfer is not approved or was already used")

    def consume(self, identity, session, kind, size, digest=None, files=None):
        with self._lock:
            item = self._get(identity, session)
            expected = item.content
            if item.status != "approved" or item.used:
                raise TransferError("Transfer is not approved or was already used")
            if (expected["type"] != kind or
                (expected["size"] is not None and expected["size"] != size) or
                expected["sha256"] != digest or expected["files"] != (files or [])):
                raise TransferError("Transfer content does not match approval")
            # Reserve before any filesystem write. Failures require a new approval.
            item.used = True
