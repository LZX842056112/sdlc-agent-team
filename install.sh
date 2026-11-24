#!/usr/bin/env bash
set -euo pipefail

PLATFORM="${1:-all}"
TARGET="${2:-.}"
HOOKS="${3:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON=python
fi

if [ "$HOOKS" = "hooks" ] || [ "$HOOKS" = "--hooks" ]; then
  "$PYTHON" "$SCRIPT_DIR/bin/install.py" --platform "$PLATFORM" --target "$TARGET" --hooks
else
  "$PYTHON" "$SCRIPT_DIR/bin/install.py" --platform "$PLATFORM" --target "$TARGET"
fi
