# QR device pairing (v1)

The existing nine digit `/api/pair` flow remains available for older clients.
New clients should use the owner approved QR flow below. Both flows issue the
same one hour, revocable Bearer session and retain the existing transfer API.

## Trust and approval

The owner interface requests `GET /api/pairing/qr` over its local HTTPS
connection. The response contains an HTTPS base URL, a random 144 bit window
identifier, a random 256 bit one-use token, expiry, the public CA certificate
in DER form and SHA-256 fingerprints. The CA fingerprint lets the phone check
the QR payload is internally consistent. The user scans this QR from the
trusted PC screen; the app then validates the HTTPS certificate chain against
that CA and still performs normal hostname verification. It must not use a
trust-all TLS manager. The leaf fingerprint is provided for extra pin checks.

The phone makes a random 256 bit polling key and a six digit display code, then
posts them with its device label and the QR window credentials to
`POST /api/pairing/claims`. The code is a human comparison value only: it is
not an authentication credential. The QR token is consumed atomically by one
claim and cannot create a session by itself.

The owner polls `GET /api/pairing/requests` from loopback. It must show the
requesting device and peer address, then ask the owner to enter the code shown
on the phone and explicitly approve. `POST /api/pairing/requests/{id}/approve`
compares the code and creates a normal session only on a match. A mismatch is
terminal. The owner can instead reject through
`POST /api/pairing/requests/{id}/reject`. The phone polls
`GET /api/pairing/claims/{id}` with `X-Pairing-Poll-Key`; the Bearer token is
returned only to that poll key, once.

QR windows and pending requests expire after 120 seconds. Claim attempts are
limited to eight per peer address per minute. Pairing state and tokens are
memory-only and are discarded on server restart. The existing local-owner
Origin/Host checks protect administrative endpoints; phone endpoints are
available only over HTTPS. Responses are marked `Cache-Control: no-store`.

## Compatibility boundary

This backend/API stage does not yet change Web Panel, TUI, PySide6 or Android
screens. Existing clients continue using `/api/pairing-code` and `/api/pair`.
The next client changes should consume this same API; no alternate pairing
backend is needed. The server CA in QR is a trust bootstrap based on the user
scanning the actual trusted PC screen. If the QR is delivered through an
untrusted remote channel, this bootstrap is insufficient and must not be
treated as authentic.
