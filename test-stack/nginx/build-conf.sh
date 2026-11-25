#!/bin/sh
# TEST ONLY. Entry point of the nginx variant's proxy (compose.nginx.yaml): assembles the nginx
# configuration from the nginx code blocks of the documentation, then starts nginx.
#
#   - this repo's README, "Reverse proxy (TLS)": the server block for mcp.example.com
#   - this repo's README, "Resource URL with a path prefix": the locations for apps.example.com
#   - restoauth's README (the copy installed with the module), "Rewrite rules for discovery": the
#     locations in the server block that serves Dolibarr (erp.example.com)
#
# The blocks are used as written. Filled in here is only what the documentation leaves to the reader:
# the certificate paths, the upstream (127.0.0.1:8131 becomes the MCP container), and the parts of the
# configuration the documentation does not cover (the server blocks of erp, sso and chat around them).
# This repo's README marks its two blocks with an HTML comment directly above the code block,
#   <!-- test-stack nginx block: mcp-server ... -->   and   <!-- test-stack nginx block: mcp-prefix ... -->
# so its text can be reworded freely. restoauth's README has no such marker yet; its block is found by
# the text '/custom/restoauth/metadata.php'.
# A block that cannot be found, or found more than once, stops the proxy, and so does a
# configuration that nginx refuses; the setup then fails.
#
#   build-conf.sh --extract-only [README]   prints the marked blocks of this repo's README (default:
#                                           ../../README.md next to this script) and exits; no nginx,
#                                           no restoauth needed. tests/test_test_stack_scripts.py uses it.
set -eu

MCP_README=/docs/mcp-server/README.md
EXTRACT_ONLY=
if [ "${1:-}" = --extract-only ]; then
  EXTRACT_ONLY=1
  MCP_README=${2:-$(dirname "$0")/../../README.md}
fi
RESTOAUTH_README=/var/www/html/custom/restoauth/README.md   # Dolibarr's custom folder (volume)
OUT=/etc/nginx/conf.d/default.conf
W=/tmp/doc-blocks

fail() { echo "[nginx-variant] $*" >&2; exit 1; }

[ -s "$MCP_README" ] || fail "$MCP_README missing"
if [ -z "$EXTRACT_ONLY" ]; then
  [ -s "$RESTOAUTH_README" ] || fail "$RESTOAUTH_README missing (is restoauth installed? the proxy starts after Dolibarr is healthy)"
else
  W=$(mktemp -d)
  trap 'rm -rf "$W"' EXIT
fi

rm -rf "$W" && mkdir -p "$W"
# Every block of a Markdown file marked '<!-- test-stack nginx block: NAME ...' (the marker line
# directly above a ```nginx fence), one file each: <prefix>-NAME.conf. A marker not directly followed
# by an nginx block, a name marked twice or a block that is not closed stops here.
extract_marked() {
  awk -v out="$W/$2" -v src="$1" '
    function die(m) { print "[nginx-variant] " src ", line " NR ": " m | "cat 1>&2"; bad = 1; exit 1 }
    match($0, /<!--[ \t]*test-stack nginx block:[ \t]*[a-z0-9-]+/) {
      if (inb) die("marker inside a code block")
      name = substr($0, RSTART, RLENGTH); sub(/.*:[ \t]*/, "", name)
      if (name in seen) die("the block \"" name "\" is marked twice")
      seen[name] = 1; want = name; next
    }
    want != "" {
      if ($0 !~ /^[ \t]*```nginx[ \t]*$/) die("the marker for \"" want "\" is not directly followed by a ```nginx block")
      f = out "-" want ".conf"; printf "" > f; inb = 1; want = ""; next
    }
    inb && /^[ \t]*```/ { inb = 0; close(f); next }
    inb { print > f }
    END {
      if (bad) exit 1
      if (want != "") die("the marker for \"" want "\" is at the end of the file")
      if (inb) die("the last marked nginx block is not closed")
    }
  ' "$1" || fail "cannot read the marked nginx blocks of $1 (see above)"
}
# The block marked NAME (from extract_marked); fails with what to look for if it is missing or empty.
marked() {
  f="$W/$2-$1.conf"
  [ -s "$f" ] || fail "no nginx block marked '<!-- test-stack nginx block: $1 -->' in $MCP_README. The marker line must sit directly above the \`\`\`nginx block; see test-stack/README.md, \"nginx variant\"."
  echo "$f"
}
# Every ```nginx block of a Markdown file, one file each: <prefix>-1.conf, <prefix>-2.conf, ...
split_blocks() {
  awk -v out="$W/$2" '
    /^[ \t]*```nginx[ \t]*$/ { n++; f = out "-" n ".conf"; inb = 1; next }
    inb && /^[ \t]*```/     { inb = 0; close(f); next }
    inb                     { print > f }
  ' "$1"
}
# The one block of <prefix> that contains <text>; fails unless there is exactly one.
pick() {
  found=$(grep -l -F -- "$1" "$W/$2"-*.conf 2>/dev/null || true)
  [ -n "$found" ] || fail "no nginx block with '$1' in the $2 README"
  [ "$(echo "$found" | wc -l)" -eq 1 ] || fail "more than one nginx block with '$1' in the $2 README"
  echo "$found"
}
# What the documentation leaves to the reader: certificate paths and the upstream address.
fill() {
  sed -e 's#^\([ \t]*ssl_certificate\)[ \t][^;]*;#\1 /certs/site.crt;#' \
      -e 's#^\([ \t]*ssl_certificate_key\)[ \t][^;]*;#\1 /certs/site.key;#' \
      -e "s#http://127\.0\.0\.1:8131#http://$2#g" "$1"
}

extract_marked "$MCP_README" mcp-server
MCP_SERVER=$(marked mcp-server mcp-server)
MCP_PREFIX=$(marked mcp-prefix mcp-server)
if [ -n "$EXTRACT_ONLY" ]; then
  echo "# ---- mcp-server ----"; cat "$MCP_SERVER"
  echo "# ---- mcp-prefix ----"; cat "$MCP_PREFIX"
  exit 0
fi
split_blocks "$RESTOAUTH_README" restoauth
DISCOVERY=$(pick '/custom/restoauth/metadata.php' restoauth)

TLS='    listen 443 ssl;
    http2 on;
    ssl_certificate     /certs/site.crt;
    ssl_certificate_key /certs/site.key;'
# Proxy settings of the stack's own server blocks (not taken from the documentation).
cat > /etc/nginx/test-stack-proxy.conf <<'EOF'
proxy_http_version 1.1;
proxy_set_header Host $host;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto https;
proxy_set_header X-Forwarded-Host $host;
proxy_buffer_size 64k;
proxy_buffers 8 64k;
proxy_busy_buffers_size 128k;
proxy_read_timeout 300s;
EOF

{
  echo "# TEST ONLY. Generated by test-stack/nginx/build-conf.sh at start-up; do not edit."
  echo "# Docker's DNS, for upstreams that start after the proxy (LibreChat)."
  echo "resolver 127.0.0.11 valid=10s ipv6=off;"
  echo
  echo "# ---- README.md, \"Reverse proxy (TLS)\", nginx ----"
  fill "$MCP_SERVER" mcp:8131
  echo "# ---- end README.md ----"
  echo
  echo "server {"
  echo "    server_name apps.example.com;"
  echo "$TLS"
  echo "    # ---- README.md, \"Resource URL with a path prefix\", nginx ----"
  fill "$MCP_PREFIX" mcp-prefix:8131 | sed 's/^/    /'
  echo "    # ---- end README.md ----"
  echo "    location / { return 404; }"
  echo "}"
  echo
  echo "server {"
  echo "    server_name erp.example.com;"
  echo "$TLS"
  echo "    client_max_body_size 50m;"
  echo "    # ---- restoauth README.md, \"Rewrite rules for discovery\", nginx ----"
  fill "$DISCOVERY" dolibarr:80 | sed 's/^/    /'
  echo "    # ---- end restoauth README.md ----"
  echo "    location / {"
  echo "        include /etc/nginx/test-stack-proxy.conf;"
  echo "        proxy_pass http://dolibarr:80;"
  echo "    }"
  echo "}"
  echo
  echo "server {"
  echo "    server_name sso.example.com;"
  echo "$TLS"
  echo "    location / {"
  echo "        include /etc/nginx/test-stack-proxy.conf;"
  echo "        proxy_pass http://keycloak:8080;"
  echo "    }"
  echo "}"
  echo
  echo "server {"
  echo "    server_name chat.example.com;"
  echo "$TLS"
  echo "    client_max_body_size 50m;"
  echo "    location / {"
  echo "        include /etc/nginx/test-stack-proxy.conf;"
  echo "        proxy_buffering off;"
  echo "        set \$librechat librechat:3080;"
  echo "        proxy_pass http://\$librechat;"
  echo "    }"
  echo "}"
} > "$OUT"

echo "[nginx-variant] assembled $OUT from $MCP_README and $RESTOAUTH_README:"
cat "$OUT"
nginx -t || fail "nginx refuses the assembled configuration (see above)"
exec /docker-entrypoint.sh nginx -g 'daemon off;'
