#!/usr/bin/env bash
# Run a flutter/dart command in the pinned Docker image (user policy: no host
# toolchain). Runs as root because the SDK cache under /sdks needs write access,
# persists the pub cache in a named volume, then restores host ownership of the
# project so files stay editable outside the container.
#
# Usage: ./fdart.sh flutter test
#        ./fdart.sh "flutter pub get && flutter analyze"
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_UID="$(id -u)"; HOST_GID="$(id -g)"
CMD="$*"
docker run --rm \
  -v cicada_pubcache:/root/.pub-cache \
  -v "$REPO:/w" -w /w/app \
  ghcr.io/cirruslabs/flutter:stable \
  bash -c "git config --global --add safe.directory '*' >/dev/null 2>&1; \
           set +e; ( $CMD ); ec=\$?; \
           chown -R $HOST_UID:$HOST_GID /w/app >/dev/null 2>&1; \
           exit \$ec"
