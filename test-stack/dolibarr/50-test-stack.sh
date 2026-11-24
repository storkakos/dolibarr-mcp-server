#!/bin/bash
# TEST ONLY. Runs in the Dolibarr container on every start (docker-run.sh, before-starting.d), after
# the image has installed the database: trusts the test CA, installs restoauth from its release ZIP
# and runs configure.php. Writes /var/www/documents/test-stack-configured on success; the container
# only turns healthy with that file, so a failed step is visible in `docker compose ps`.
set -euo pipefail
MARKER=/var/www/documents/test-stack-configured
rm -f "$MARKER"

# The test CA: Dolibarr calls Keycloak (openid_connect) over HTTPS from the server.
cp /certs/ca.crt /usr/local/share/ca-certificates/dolibarr-mcp-test-ca.crt
update-ca-certificates >/dev/null 2>&1

# restoauth from the release ZIP, the way Dolibarr's module upload installs it: the ZIP's
# restoauth/ folder replaces htdocs/custom/restoauth. Done again when the ZIP changed (another
# version, or a local ZIP or checkout with new content), since htdocs/custom is a volume.
ZIP="/opt/restoauth/module_restoauth-$RESTOAUTH_VERSION.zip"
DEST=/var/www/html/custom
STAMP="$DEST/.restoauth-zip.sha256"
SUM="$(sha256sum "$ZIP" | cut -d' ' -f1)"
if [ "$(cat "$STAMP" 2>/dev/null)" != "$SUM" ] || ! grep -qs "version = '$RESTOAUTH_VERSION'" "$DEST/restoauth/core/modules/modRestOAuth.class.php"; then
  echo "[test-stack] installing restoauth $RESTOAUTH_VERSION from $(basename "$ZIP") (sha256 $SUM)"
  rm -rf "$DEST/restoauth"
  php -r '$z = new ZipArchive(); if ($z->open($argv[1]) !== true || !$z->extractTo($argv[2])) { exit(1); }' "$ZIP" "$DEST"
  chown -R www-data:www-data "$DEST/restoauth"
  echo "$SUM" > "$STAMP"
fi

echo "[test-stack] configuring Dolibarr"
cd /var/www/html
runuser -u www-data -- php /opt/test-stack/configure.php
touch "$MARKER"
echo "[test-stack] Dolibarr configured"
