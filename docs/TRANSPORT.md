# HTTPS transport: scope and setup

Dev-Drop now requires HTTPS everywhere, including desktop loopback traffic.
There is no HTTP listener, redirect bootstrap, certificate-warning exception,
automatic CA installation, or trust-on-first-use from the network. Missing TLS
configuration refuses startup. Launch through `devdrop.py` or `devdrop_gui.py`;
starting `uvicorn app.main:app` without TLS only returns HTTP 426, never the app.
Keep proxy headers disabled; a reverse proxy is outside this stage's trust model.

## Choice of transport

| Approach | Browser / first-trust limits | Decision |
| --- | --- | --- |
| Self-signed HTTPS + fingerprint | A desktop/native client can pin before sending. A normal web page cannot inspect/pin the TLS certificate before loading. A self-signed warning alone does not establish identity or prevent MITM. | Not the mobile bootstrap. |
| HTTPS with a dedicated, locally trusted CA | Standard TLS, chain/date/SAN validation. Requires installing the verified CA on each phone/browser before connecting. | Implemented infrastructure. GUI also pins the exact leaf certificate. |
| Application encryption using Web Crypto | `crypto.subtle` needs a secure context; ordinary LAN HTTP is not one. HTTP-delivered JavaScript could be replaced, including its cryptography and key exchange. | Not an alternative bootstrap. No custom encryption protocol. |

Sources: [Web Crypto secure contexts](https://developer.mozilla.org/en-US/docs/Web/API/Crypto),
[Chrome local trust](https://chromium.googlesource.com/chromium/src/+/HEAD/net/data/ssl/chrome_root_store/faq.md),
[Firefox Android CA setting](https://bugzilla.mozilla.org/show_bug.cgi?id=1910173),
[Python TLS verification](https://docs.python.org/3.14/library/ssl.html),
[Uvicorn HTTPS options](https://uvicorn.dev/settings/).

## Provision certificates before starting

Use an existing trusted certificate issuer or a dedicated private CA managed
outside Dev-Drop. The application does not generate or keep a CA private key.
Certificate issuance tools are an administrator prerequisite, not a new runtime
Python dependency. The server private key must be encrypted PKCS#8 PEM, with a
strong unique password. The password is requested at startup (masked in the GUI)
and is retained in process memory for TLS use, never written to configuration.

For example, on a trusted/offline machine using OpenSSL (commands prompt for key
passwords; do not put production passwords in command arguments):

```text
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -aes-256-cbc -out ca-key.pem
openssl req -new -x509 -key ca-key.pem -sha256 -days 3650 -out ca.pem -subj "/CN=DevDrop Dedicated Local CA" -addext "basicConstraints=critical,CA:TRUE,pathlen:0" -addext "keyUsage=critical,keyCertSign,cRLSign"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -aes-256-cbc -out server-key.pem
openssl req -new -key server-key.pem -out server.csr -subj "/CN=DevDrop"
```

Create `server.ext`, replacing the LAN address with the computer's actual address:

```ini
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:127.0.0.1,IP:192.168.1.50,DNS:localhost
```

Then issue the server certificate:

```text
openssl x509 -req -in server.csr -CA ca.pem -CAkey ca-key.pem -CAcreateserial -sha256 -days 90 -extfile server.ext -out server.pem
openssl x509 -in server.pem -noout -fingerprint -sha256
openssl x509 -in ca.pem -noout -fingerprint -sha256
```

Only `server.pem` (leaf first, then intermediates if needed), encrypted
`server-key.pem` and the public `ca.pem` belong on the server. Keep the CA private
key offline; never put it on a phone or distribute it. Neither key belongs in
Git, build artifacts or the web directory. Keep TLS files outside the session
root so they cannot appear in transfer counters/history or be deleted with a
session. On POSIX use owner-only storage and `chmod 600 server-key.pem` (enforced).
On Windows use an owner-only NTFS directory under the user's profile, remove
broad inherited access using Windows Security/Advanced permissions, and retain
only the owner and necessary system/admin access. Encryption is enforced on both
platforms; Windows ACL inspection/enforcement is manual in this stage. Protect
source copies and backups too; encryption does not protect a running process
from malware with the same user privileges.

Create `tls.json` under the usual DevDrop configuration directory:
`%APPDATA%/DevDrop` on Windows, otherwise `~/.config/DevDrop`. Alternatively set
`DEVDROP_TLS_CONFIG` to its path. Use absolute paths (JSON Windows backslashes must
be escaped, or use forward slashes):

```json
{
  "certificate": "C:/Users/OWNER/AppData/Roaming/DevDrop/tls/server.pem",
  "key": "C:/Users/OWNER/AppData/Roaming/DevDrop/tls/server-key.pem",
  "ca": "C:/Users/OWNER/AppData/Roaming/DevDrop/tls/ca.pem",
  "host": "192.168.1.50",
  "sha256": "REPLACE_WITH_64_HEX_DIGITS_OF_SERVER_CERTIFICATE_SHA256_WITHOUT_COLONS"
}
```

`host` is the LAN identity in the certificate SAN. The certificate must also have
IP SAN `127.0.0.1` for the GUI. The GUI uses a dedicated CA context, normal
hostname validation and the configured leaf pin *before* sending HTTP headers.
It ignores environment proxies and refuses redirects. Server startup verifies
the key/password, certificate chain, validity, SANs and leaf pin by an in-memory
TLS handshake. Both launchers configure Uvicorn for TLS, proxy headers disabled,
TLS 1.2 minimum (CPython secure server defaults), and modern ECDHE ciphers.

## First trusted phone connection

1. Obtain the **public CA certificate** over a trusted independent channel, such
   as USB directly from the owner's computer. Verify its SHA-256 against the
   owner's trusted/offline display before installation. A CA or fingerprint
   downloaded over unauthenticated LAN HTTP is not an identity proof.
2. Install this specific CA for website/server authentication in the phone's
   trusted certificate store. It is a CA certificate, not a Wi-Fi/client identity
   certificate. Menu names vary by Android vendor/version. Installing a CA is a
   security-sensitive change affecting other sites too; use a dedicated CA and
   remove it when no longer needed.
3. Open only the configured **HTTPS** address from the owner's QR/display. A
   certificate warning means stop: check trust, date and SAN/address. Do not
   bypass the warning. Only after a warning-free, verified connection enter the
   pairing code. Tokens and transfers then travel within TLS; the existing
   Bearer/session and separate owner-approval rules still apply.

Android Chrome consults locally managed trust; a correctly installed CA and
matching SAN are prerequisites, not an automatic guarantee for every vendor's
configuration. Firefox Android may additionally require its **Use third party
CA certificates** setting and a restart; availability varies by build/version.
If that browser does not accept the installed CA, it is unsupported by this
setup: use a browser that validates it correctly, never a warning exception.
Windows browsers also need the CA installed in their relevant trust store; the
Python GUI uses its explicit CA file instead. No physical Android/Windows browser
verification has been performed by automated Linux tests.

## Identity changes and remaining boundaries

QR/URL uses configured `host`, not an unchecked current IP. Prefer a DHCP
reservation or a stable locally resolvable DNS name included in SAN. With an IP
SAN, changing IP requires reissuing a certificate and updating host/pin. DNS
identity can survive an IP change if local name resolution and SAN still match.
Discovery remains unauthenticated metadata and advertises HTTPS only; the web
client refuses cross-origin discovery navigation. It is not a trust bootstrap.

Changing a server certificate causes the GUI pin check to refuse connection.
There is no automatic acceptance or HTTP fallback. Stop the server, verify the
replacement certificate out of band, update certificate/key/host and the leaf
pin, and restart. Renewals under the same trusted CA ordinarily need no phone CA
reinstallation; browsers verify CA/hostname/date, **not** the GUI's exact leaf
pin. A new CA requires a new trusted out-of-band installation/removal procedure.
CA/key compromise is not solved by pinning a web page: manage renewal/revocation
outside this application. CRL/OCSP automation is not implemented.

The server rejects any plaintext HTTP ASGI request before reading its body, but
cannot prevent someone using an unrelated HTTP client from putting a secret on
the wire. App clients never do that. Likewise, visiting an attacker-controlled
HTTP clone is outside the trusted HTTPS workflow. Do not start a plaintext proxy
or distribute a page over HTTP. No automatic LAN bootstrap in an untrusted network
is claimed. Keep single-process approvals, loopback owner trust and the existing
file/history atomicity limitations documented above.

Tests generate temporary test-only keys/certificates using OpenSSL CLI, exercise
verification failures and real loopback HTTPS uploads. No production identities
are generated, no trust store is changed, and no public-network listener is used.
