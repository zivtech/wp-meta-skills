#!/usr/bin/env bash
# Builds the Lane H stack image. See Dockerfile's header for the design
# sections this implements.
#
# Usage: build.sh [image-tag]
set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TAG="${1:-localwp-tool-value-stack:dev}"

docker build -t "$TAG" -f "$STACK_DIR/Dockerfile" "$STACK_DIR"
echo "build.sh: built $TAG"
