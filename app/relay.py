"""Relay orchestration using existing approvals and file-offer storage."""
import threading
import time
from dataclasses import dataclass

from pydantic import ConfigDict, Field
from app.transfer_requests import TransferDescription, TransferError
from app.file_offers import OfferError


class RelayCreate(TransferDescription):
    model_config = ConfigDict(extra="forbid")
    recipient_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class RelayError(ValueError):
    pass


@dataclass
class RelayTransfer:
    id: str
    sender: str
    recipient: str
    sender_id: str
    recipient_id: str
    filename: str
    created_at: float
    expires_at: float
    status: str = "pending"
    offer_id: str | None = None

    def public(self):
        return {key: value for key, value in vars(self).items() if key not in {"sender", "recipient"}}


class RelayService:
    def __init__(self, approvals, offers, session_valid, lifetime=300, clock=time.time):
        self.approvals, self.offers, self.session_valid = approvals, offers, session_valid
        self.lifetime, self.clock = lifetime, clock
        self._lock = threading.RLock()
        self._relays = {}

    def _sync(self, relay):
        if relay.status in {"pending", "approved"}:
            try:
                relay.status = self.approvals.state(relay.id, relay.sender)["status"]
            except TransferError:
                relay.status = "expired"
        if relay.offer_id is not None:
            try:
                relay.status = self.offers.state(relay.offer_id)["status"]
            except OfferError:
                if relay.status not in {"sent", "failed", "rejected", "cancelled", "expired"}:
                    relay.status = "expired"
            if relay.status == "pending":
                relay.status = "offered"
        if self.clock() >= relay.expires_at and relay.status in {"pending", "approved", "uploading", "offered", "accepted", "streaming"}:
            relay.status = "expired"
            if relay.offer_id:
                try:
                    self.offers.cancel(relay.offer_id)
                except OfferError:
                    pass
        return relay

    def _get(self, identity, session):
        relay = self._relays.get(identity)
        if relay is None or session not in {relay.sender, relay.recipient}:
            raise RelayError("Relay is unavailable")
        return self._sync(relay)

    def create(self, sender, recipient, sender_id, description):
        with self._lock:
            now = self.clock()
            self._relays = {key: item for key, item in self._relays.items() if item.expires_at + 3600 > now}
            if len(self._relays) >= 100:
                raise RelayError("Too many relays")
            if sender == recipient or not self.session_valid(sender) or not self.session_valid(recipient):
                raise RelayError("Recipient session is unavailable")
            if description.type != "file" or len(description.files) != 1:
                raise RelayError("Choose exactly one file for relay")
            # Owner sees the canonical receiving session, not a claimed device name.
            description = description.model_copy(update={"sender": f"Session {sender_id[:8]}",
                "description": f"Relay to session {description.recipient_id[:8]}: {description.description}"[:500]})
            approval = self.approvals.create(sender, description)
            relay = RelayTransfer(approval["id"], sender, recipient, sender_id, description.recipient_id,
                                  description.files[0].name, now, now + self.lifetime)
            self._relays[relay.id] = relay
            return relay.public()

    def state(self, identity, session):
        with self._lock:
            return self._get(identity, session).public()

    def list(self, sender):
        with self._lock:
            return [self._sync(relay).public() for relay in self._relays.values() if relay.sender == sender]

    def check_upload(self, identity, sender):
        with self._lock:
            relay = self._get(identity, sender)
            if sender != relay.sender or relay.status != "approved" or not self.session_valid(relay.recipient):
                raise RelayError("Relay upload is not approved or recipient is unavailable")
            self.approvals.check_approved(identity, sender, relay.recipient_id)

    def upload(self, identity, sender, manifest, source):
        with self._lock:
            self.check_upload(identity, sender)
            relay = self._relays[identity]
            self.approvals.consume(identity, sender, "file", sum(item["size"] for item in manifest),
                                   files=manifest, recipient_id=relay.recipient_id)
            relay.status = "uploading"
        offer = None
        try:
            offer = self.offers.create_stream(source, relay.filename, relay.recipient, relay.recipient_id,
                deadline=relay.expires_at, sender=f"Browser session {relay.sender_id[:8]}", published=False)
            with self._lock:
                self._sync(relay)
                if (relay.status != "uploading" or not self.session_valid(sender) or
                    not self.session_valid(relay.recipient)):
                    raise RelayError("Relay cancelled, expired or session unavailable")
                self.offers.publish(offer["id"])
                relay.offer_id, relay.status = offer["id"], "offered"
                return relay.public()
        except Exception:
            if offer is not None:
                try:
                    self.offers.discard_prepared(offer["id"])
                except OfferError:
                    pass
            with self._lock:
                if relay.status == "uploading":
                    relay.status = "failed"
            raise

    def cancel(self, identity, sender):
        with self._lock:
            relay = self._get(identity, sender)
            if sender != relay.sender or relay.status not in {"pending", "approved", "uploading", "offered", "accepted", "streaming"}:
                raise RelayError("Relay cannot be cancelled")
            if relay.offer_id:
                self.offers.cancel(relay.offer_id)
            else:
                try:
                    self.approvals.cancel(identity, sender)
                except TransferError:
                    pass  # Already spent while copying; revoke publication instead.
            relay.status = "cancelled"
            return relay.public()
