#!/usr/bin/env bash
set -euo pipefail

TLS_DIR="$HOME/.config/DevDrop/tls"
CA_DIR="$HOME/.config/DevDrop/ca"
CONFIG_FILE="$HOME/.config/DevDrop/tls.json"

if [[ -e "$CONFIG_FILE" || -e "$TLS_DIR/tls.json" || -e "$TLS_DIR/server-key.pem" || -e "$CA_DIR/ca-key.pem" ]]; then
    printf 'TLS files already exist. Refusing to overwrite them.\n' >&2
    printf 'Config directory: %s\n' "$HOME/.config/DevDrop" >&2
    exit 1
fi

command -v openssl >/dev/null || { printf 'OpenSSL is required.\n' >&2; exit 1; }
mkdir -p "$TLS_DIR" "$CA_DIR"
chmod 700 "$HOME/.config/DevDrop" "$TLS_DIR" "$CA_DIR"

while :; do
    IFS= read -r -s -p 'Choose a strong passphrase for the encrypted TLS keys: ' DEVDROP_KEYPASS
    printf '\n'
    if [[ -z "$DEVDROP_KEYPASS" ]]; then
        printf 'Passphrase cannot be empty.\n' >&2
        continue
    fi
    IFS= read -r -s -p 'Repeat passphrase: ' DEVDROP_KEYPASS_CONFIRM
    printf '\n'
    [[ "$DEVDROP_KEYPASS" == "$DEVDROP_KEYPASS_CONFIRM" ]] && break
    printf 'Passphrases did not match. Try again.\n' >&2
done
unset DEVDROP_KEYPASS_CONFIRM
export DEVDROP_KEYPASS

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -aes-256-cbc \
    -pass env:DEVDROP_KEYPASS -out "$CA_DIR/ca-key.pem"
chmod 600 "$CA_DIR/ca-key.pem"
openssl req -new -x509 -key "$CA_DIR/ca-key.pem" -passin env:DEVDROP_KEYPASS \
    -sha256 -days 3650 -out "$CA_DIR/ca.pem" -subj '/CN=DevDrop Local Test CA' \
    -addext 'basicConstraints=critical,CA:TRUE,pathlen:0' \
    -addext 'keyUsage=critical,keyCertSign,cRLSign'

openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -aes-256-cbc \
    -pass env:DEVDROP_KEYPASS -out "$TLS_DIR/server-key.pem"
chmod 600 "$TLS_DIR/server-key.pem"
openssl req -new -key "$TLS_DIR/server-key.pem" -passin env:DEVDROP_KEYPASS \
    -out "$TLS_DIR/server.csr" -subj '/CN=DevDrop Local Test Server'
cat > "$TLS_DIR/server.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=IP:127.0.0.1,DNS:localhost
EOF
openssl x509 -req -in "$TLS_DIR/server.csr" -CA "$CA_DIR/ca.pem" \
    -CAkey "$CA_DIR/ca-key.pem" -passin env:DEVDROP_KEYPASS -CAcreateserial \
    -sha256 -days 90 -extfile "$TLS_DIR/server.ext" -out "$TLS_DIR/server.pem"

FINGERPRINT=$(openssl x509 -in "$TLS_DIR/server.pem" -noout -fingerprint -sha256 \
    | sed 's/.*=//; s/://g' | tr 'A-F' 'a-f')
FINGERPRINT="$FINGERPRINT" python3 - "$TLS_DIR" "$CONFIG_FILE" <<'PY'
import json
import os
import pathlib
import sys

tls_dir = pathlib.Path(sys.argv[1])
config_path = pathlib.Path(sys.argv[2])
data = {
    "certificate": str(tls_dir / "server.pem"),
    "key": str(tls_dir / "server-key.pem"),
    "ca": str(tls_dir.parent / "ca" / "ca.pem"),
    "host": "127.0.0.1",
    "sha256": os.environ["FINGERPRINT"],
}
config = config_path
config.parent.mkdir(parents=True, exist_ok=True)
config.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
config.chmod(0o600)
PY

unset DEVDROP_KEYPASS
printf '\nLocal HTTPS identity is ready.\n'
printf 'CA certificate: %s\n' "$CA_DIR/ca.pem"
printf 'CA SHA-256: '
openssl x509 -in "$CA_DIR/ca.pem" -noout -fingerprint -sha256 | sed 's/.*=//'
printf 'TLS config: %s\n' "$CONFIG_FILE"
printf '\nNext: ./run-panel.sh  (enter the same passphrase at the startup prompt)\n'
printf 'This identity is for this PC only; it does not include your LAN IP or configure Android trust.\n'
