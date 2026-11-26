# TEST ONLY. Dolibarr 23 (official image, Apache + mod_php) with the restoauth release ZIP (or a
# local ZIP or checkout, see stage 1), the discovery rewrite rule and the test stack's configuration
# step.

# The one place that pins restoauth. Override for a test with
#   docker compose build --build-arg RESTOAUTH_VERSION=X.Y.Z dolibarr
ARG RESTOAUTH_VERSION=0.3.1

# Stage 1: the release ZIP module_restoauth-<version>.zip, from one of three sources:
# - default: the asset of the GitHub release v<version> if that release has the ZIP attached;
#   otherwise built from the tag with the repo's own scripts/build-release-zip.sh (same bytes for
#   the same tag). Never a loose copy of the module.
# - a local folder with that ZIP in it (RESTOAUTH_LOCAL in compose.yaml, the build context
#   `restoauth-local`): the ZIP is taken as it is.
# - a local restoauth checkout (the same build context): the ZIP is built from the checkout's
#   working tree with `git archive`, like build-release-zip.sh, so tracked files with their
#   uncommitted changes are in it, untracked files and export-ignore files are not.
# The default build context `restoauth-local` is the folder no-local-restoauth/ with only its
# marker file in it. Whatever the source, the build stops unless the ZIP's module descriptor
# carries RESTOAUTH_VERSION.
FROM alpine:3.22.2 AS restoauth
ARG RESTOAUTH_VERSION
ARG RESTOAUTH_REPO=https://github.com/storkakos/dolibarr-restoauth
RUN apk add --no-cache bash curl git unzip >/dev/null
COPY --from=restoauth-local . /local/
RUN set -eu; V="$RESTOAUTH_VERSION"; ZIP="module_restoauth-$V.zip"; \
    DESC=core/modules/modRestOAuth.class.php; \
    if [ -f /local/.no-local-restoauth ]; then \
      if curl -fsSL -o "/$ZIP" "$RESTOAUTH_REPO/releases/download/v$V/$ZIP"; then \
        echo "restoauth: release asset $ZIP of v$V"; \
        if [ "$V" = "0.3.1" ]; then \
          EXPECTED="71039e30a823bebe7a9c621da7bd5c241109e758e9b11fdc49dd32897bd1af7d"; \
          ACTUAL="$(sha256sum "/$ZIP" | cut -d' ' -f1)"; \
          if [ "$ACTUAL" != "$EXPECTED" ]; then \
            echo "restoauth: $ZIP sha256 mismatch: expected $EXPECTED, got $ACTUAL" >&2; exit 1; \
          fi; \
          echo "restoauth: $ZIP sha256 verified"; \
        fi; \
      else \
        echo "restoauth: no release asset for v$V, building $ZIP from the tag"; \
        git -c advice.detachedHead=false clone -q --depth 1 --branch "v$V" "$RESTOAUTH_REPO.git" /src; \
        OUT_DIR=/ bash /src/scripts/build-release-zip.sh "v$V"; \
      fi; \
    elif [ -f "/local/$DESC" ]; then \
      [ -d /local/.git ] || { echo "restoauth: the local checkout has no .git folder; give a git checkout or a folder with $ZIP" >&2; exit 1; }; \
      git config --global --add safe.directory /local; \
      git -C /local rev-parse --verify -q HEAD >/dev/null || { echo "restoauth: the local checkout has no commit" >&2; exit 1; }; \
      REF="$(git -C /local -c user.name=test-stack -c user.email=test-stack@localhost stash create || true)"; \
      if [ -n "$REF" ]; then STATE="with uncommitted changes"; else REF=HEAD; STATE="clean"; fi; \
      echo "restoauth: building $ZIP from the local checkout at $(git -C /local rev-parse --short HEAD), $STATE"; \
      git -C /local archive --format=zip --prefix=restoauth/ -o "/$ZIP" "$REF"; \
    elif [ -f "/local/$ZIP" ]; then \
      echo "restoauth: local ZIP $ZIP"; \
      cp "/local/$ZIP" "/$ZIP"; \
    else \
      echo "restoauth: the local folder has neither $ZIP nor a restoauth checkout ($DESC). Its files: $(ls -A /local | tr '\n' ' ')" >&2; \
      exit 1; \
    fi; \
    FOUND="$(unzip -p "/$ZIP" "restoauth/$DESC" 2>/dev/null | sed -n "s/.*this->version = '\([^']*\)'.*/\1/p" | head -n 1)"; \
    [ "$FOUND" = "$V" ] \
      || { echo "restoauth: $ZIP has no module descriptor for version $V (its descriptor says '${FOUND:-none}'); build with --build-arg RESTOAUTH_VERSION=<the module's version>" >&2; exit 1; }; \
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
