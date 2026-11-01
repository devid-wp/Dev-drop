# Release Candidate 1 manual verification

Automated unit, ASGI, and loopback TLS tests do not replace testing on a real PC
and Android phone. Run this checklist on the target Windows/Linux PC and the
Android versions intended for release. Do not bypass a certificate warning or
use an HTTP URL during these checks.

## Prepare the PC

1. Start Dev-Drop without preconfiguring TLS. Accept automatic local HTTPS
   setup; confirm the HTTPS address and QR appear. Existing TLS identities
   should be reused.
2. Start the existing PySide6 desktop app (`python devdrop_gui.py`) or the
   existing server launcher (`python devdrop.py`). Use only one process on the
   configured port. Confirm the UI reports HTTPS and shows a live QR.
3. Ensure the PC has free space in its configured session directory. For
   outgoing PC-to-phone offers, also ensure free space for a private snapshot;
   preparation temporarily copies the source file.

## Pair and check session lifecycle

1. On Android, scan the QR shown on the PC. Compare the six digit code on the
   phone with the request on the PC, enter it on the PC, and explicitly approve.
2. Confirm the Android app reaches Connected and the PC lists one session.
3. Attempt a mismatched short code and confirm the request is terminally
   rejected. Reuse a scanned QR token from another Android install/profile; it
   must be rejected. Scan a fresh QR for the intended device.
4. Disconnect in Android while online. The device should disappear from the
   PC recipient list after refresh. Pair again and confirm a new session ID.
   Also revoke a session from the local Web Panel Devices view. The Android
   reconnect must require a fresh QR. An offline Android disconnect cannot
   revoke remotely; the server session remains valid until expiry or restart.
5. Change the PC address to a hostname/IP absent from the certificate SAN or
   temporarily use an untrusted CA in a test profile. Android must refuse before
   sending pairing/session credentials.

## Verify both file directions

1. **Android to PC:** select one small file and then multiple files. Confirm the
   PC explicitly asks for owner approval for every request. Reject one request
   and approve another. Compare the received bytes with the originals.
2. **PC to Android:** select the Android session in **Send to browser**, offer a
   file, then inspect it under **Incoming files**. Decline one offer and accept
   another. Android must ask for a save destination before accepting. Verify
   the saved file against the source and confirm the PC offer reaches
   **received** only after Android closes the SAF document and posts its
   verified size/SHA-256 receipt.
3. Cancel during an active transfer and check that partial Android output is
   removed, the offer is not reusable, and the sender can create a fresh offer.
   Also try a destination with insufficient space or revoked SAF access; the
   UI must report an error and must not report completion.
4. Repeat with a large file while watching PC and Android memory use. Verify
   progress advances only with bytes actually written and the final hash
   matches. No artificial size limit is configured, but storage availability
   and provider behavior still bound practical transfers.
5. Check the desktop UI, CLI/TUI, and Web Panel show a server-side `sent` state
   separately from Android's `received` state. Browser downloads do not post a
   receipt and therefore remain `sent`.

## Limits to record

- QR pairing tokens are one-use and expire after two minutes. The short numeric
  code is a human check only; it is not an authentication secret.
- Bearer sessions are process-local and last at most one hour. There is no
  background keepalive or presence protocol. Server restart invalidates them.
- A disconnect while offline clears Android's local credentials but cannot
  revoke the token on the PC until expiry/restart.
- Disconnect or expiry cancels that session's pending, accepted, and active
  PC-to-phone offers and removes their snapshots. A completed server stream
  (`sent`) remains available for a verified receipt.
- Accepted downloads are one-use and cannot resume. If the download fails,
  request a fresh offer. If the full file was saved but receipt networking
  failed, use **Retry server confirmation** while the same session is valid; do
  not download again. If that session is revoked before retry, the offer cannot
  be confirmed with a replacement session and the sender must create a fresh
  offer.
- File offers and incoming transfer approvals are process-local; server
  restart loses their states. A hard crash may leave temporary private files.
- Successful automated tests are not evidence that physical device onboarding,
  OEM SAF providers, sleep/resume, or Wi-Fi roaming work on every target.

Record PC OS/build, Android version/device, tested TLS address, file sizes,
outcomes, and any device-specific failures before release.
