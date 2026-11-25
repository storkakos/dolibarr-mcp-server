#!/bin/sh
# TEST ONLY. Creates certs/ca.crt (test CA) and certs/site.crt (erp/sso/mcp/chat/apps.example.com;
# apps.example.com is only used by the nginx variant). certs/ is git-ignored.
#
# An existing certs/ folder is kept as long as site.crt covers every hostname below and is valid for
# at least another day. Otherwise site.crt is issued again by the existing CA (so a browser that
# trusts certs/ca.crt keeps trusting it), or, without the CA's key, the whole folder is made again.
# Delete certs/ to start over.
set -eu
HOSTS="erp.example.com sso.example.com mcp.example.com chat.example.com apps.example.com"
cd "$(dirname "$0")"
mkdir -p certs
cd certs

# The hostnames of $HOSTS that site.crt lacks (all of them if it cannot be read).
missing_hosts() {
  sans=$(openssl x509 -in site.crt -noout -text 2>/dev/null \
    | sed -n '/Subject Alternative Name/{n;p;}' | tr ',' '\n' | sed 's/^[ \t]*//')
  for h in $HOSTS; do
    printf '%s\n' "$sans" | grep -qxF "DNS:$h" || printf '%s ' "$h"
  done
}

new_ca() {
  openssl req -x509 -newkey rsa:2048 -nodes -days 365 -subj "/CN=dolibarr-mcp test CA" \
    -keyout ca.key -out ca.crt \
    -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "subjectKeyIdentifier=hash" 2>/dev/null
}

new_site() {
  san=""
  for h in $HOSTS; do san="${san:+$san,}DNS:$h"; done
  openssl req -newkey rsa:2048 -nodes -subj "/CN=example.com" -keyout site.key -out site.csr 2>/dev/null
  cat > ext.cnf <<EOT
subjectAltName=$san
basicConstraints=CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
authorityKeyIdentifier=keyid
EOT
  openssl x509 -req -in site.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 365 -extfile ext.cnf \
    -out site.crt 2>/dev/null
  rm -f site.csr ext.cnf ca.srl
}

ca_usable() {
  [ -f ca.crt ] && [ -f ca.key ] && openssl x509 -in ca.crt -noout -checkend 86400 >/dev/null 2>&1
}

if [ -f ca.crt ] && [ -f site.crt ] && [ -f site.key ]; then
  missing=$(missing_hosts)
  if [ -z "$missing" ] && openssl x509 -in site.crt -noout -checkend 86400 >/dev/null 2>&1; then
    echo "certs/ already exists and covers every hostname, keeping it"
    exit 0
  fi
  if [ -n "$missing" ]; then why="lacks ${missing% }"; else why="expires within a day"; fi
  if ca_usable; then
    new_site
    echo "certs/site.crt $why: issued it again with the existing test CA"
  else
    rm -f ca.crt ca.key site.crt site.key
    new_ca
    new_site
    echo "certs/site.crt $why and the test CA cannot issue a new one: made certs/ again (trust the new certs/ca.crt)"
  fi
else
  rm -f ca.crt ca.key site.crt site.key
  new_ca
  new_site
  echo "created certs/ca.crt and certs/site.crt"
fi
# Readable by the containers' users (Caddy, the MCP server runs as UID 10001).
chmod 644 ca.crt site.crt site.key

# Never end without a certificate for every hostname.
missing=$(missing_hosts)
[ -z "$missing" ] || { echo "make-certs.sh: certs/site.crt still lacks ${missing% }" >&2; exit 1; }
