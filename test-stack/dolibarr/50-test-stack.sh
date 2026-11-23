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
# restoauth/ folder replaces htdocs/custom/restoauth. Done again when the pinned version changed.
ZIP="/opt/restoauth/module_restoauth-$RESTOAUTH_VERSION.zip"
DEST=/var/www/html/custom
if ! grep -qs "version = '$RESTOAUTH_VERSION'" "$DEST/restoauth/core/modules/modRestOAuth.class.php"; then
  echo "[test-stack] installing restoauth $RESTOAUTH_VERSION from $(basename "$ZIP")"
  rm -rf "$DEST/restoauth"
  php -r '$z = new ZipArchive(); if ($z->open($argv[1]) !== true || !$z->extractTo($argv[2])) { exit(1); }' "$ZIP" "$DEST"
  chown -R www-data:www-data "$DEST/restoauth"
fi

echo "[test-stack] configuring Dolibarr"
cd /var/www/html
runuser -u www-data -- php /opt/test-stack/configure.php
touch "$MARKER"
echo "[test-stack] Dolibarr configured"
