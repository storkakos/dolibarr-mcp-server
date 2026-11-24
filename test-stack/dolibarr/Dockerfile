# TEST ONLY. Dolibarr 23 (official image, Apache + mod_php) with the restoauth release ZIP, the
# discovery rewrite rule and the test stack's configuration step.

# The one place that pins restoauth. Override for a test with
#   docker compose build --build-arg RESTOAUTH_VERSION=X.Y.Z dolibarr
ARG RESTOAUTH_VERSION=0.2.2

# Stage 1: the release ZIP module_restoauth-<version>.zip. Taken from the GitHub release of tag
# v<version> if that release has the ZIP attached; otherwise built from the tag with the repo's own
# scripts/build-release-zip.sh (same bytes for the same tag). Never a loose copy of the module.
FROM alpine:3.22.2 AS restoauth
ARG RESTOAUTH_VERSION
ARG RESTOAUTH_REPO=https://github.com/storkakos/dolibarr-restoauth
RUN apk add --no-cache bash curl git unzip >/dev/null
RUN set -eu; V="$RESTOAUTH_VERSION"; ZIP="module_restoauth-$V.zip"; \
    if curl -fsSL -o "/$ZIP" "$RESTOAUTH_REPO/releases/download/v$V/$ZIP"; then \
      echo "restoauth: release asset $ZIP of v$V"; \
    else \
      echo "restoauth: no release asset for v$V, building $ZIP from the tag"; \
      git -c advice.detachedHead=false clone -q --depth 1 --branch "v$V" "$RESTOAUTH_REPO.git" /src; \
      OUT_DIR=/ bash /src/scripts/build-release-zip.sh "v$V"; \
    fi; \
    unzip -p "/$ZIP" restoauth/core/modules/modRestOAuth.class.php | grep -q "version = '$V'" \
      || { echo "restoauth: $ZIP has no module descriptor for version $V" >&2; exit 1; }; \
    mkdir /out && mv "/$ZIP" /out/

# Stage 2: Dolibarr.
FROM dolibarr/dolibarr:23.0.4
ARG RESTOAUTH_VERSION
ENV RESTOAUTH_VERSION=$RESTOAUTH_VERSION
RUN a2enmod rewrite remoteip >/dev/null
COPY dolibarr.conf /etc/apache2/sites-available/000-default.conf
COPY --from=restoauth /out/ /opt/restoauth/
COPY configure.php /opt/test-stack/configure.php
# Run by the image's docker-run.sh on every start, after the database is installed and before Apache.
COPY 50-test-stack.sh /var/www/scripts/before-starting.d/50-test-stack.sh
# Healthy once 50-test-stack.sh finished without an error and Apache answers.
HEALTHCHECK --interval=5s --timeout=5s --start-period=600s --retries=3 \
    CMD test -f /var/www/documents/test-stack-configured && curl -fsS -o /dev/null http://127.0.0.1/index.php
