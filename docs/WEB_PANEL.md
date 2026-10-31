# Local Web Panel

Start the existing server, then open `https://127.0.0.1:<port>/panel` on the
same computer. The browser must already trust the provisioned Dev-Drop CA. The
panel is served by FastAPI in the same process; it does not start a second
server. The existing `/` browser client remains the phone interface.

The page and its assets require a direct loopback connection and a loopback
`Host`. HTTP is rejected. Responses use `no-store`, a restrictive CSP, and frame
protections. Data comes from `/api/status`, `/api/discover`,
`/api/recipient-sessions`, `/api/transfer-requests`, `/api/outgoing-offers`,
`/api/history`, and (only when Security is opened) `/api/pairing-code`.
Pairing-code data is removed from the status object before the UI renders it.

Transfer decisions post to the existing `/api/transfer-requests/{id}/approve`
or `/reject` routes after an explicit review dialog. The panel does not approve
requests automatically. Existing server-side direct-peer, `Host`, and `Origin`
checks remain authoritative. Sensitive local status/history/pairing responses
are marked `no-store`.

The backend reports real PC-to-browser offer states and `sent_bytes`; those are
the only transfer progress values shown. The backend does not expose progress
for incoming phone uploads. History contains successfully saved incoming files
only. Settings display the configured port and session directory from the
existing status API; edits remain available through `devdrop config`. The
browser API does not expose certificate fingerprint or expiry, so the Security
page reports that limit instead of guessing.
