#!/usr/bin/env bash
# Point this repo's git hooks at scripts/lead/hooks/. core.hooksPath is a
# relative path, so every worktree runs the hooks from its own checkout, and the hooks
# stay under version control. Idempotent; `--uninstall` removes the setting.
#
#   scripts/lead/install-hooks.sh [--uninstall]
set -euo pipefail
root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
if [ "${1:-}" = --uninstall ]; then
  git -C "$root" config --unset core.hooksPath || true
  echo "hooks: core.hooksPath unset"
  exit 0
fi
chmod +x "$root"/scripts/lead/hooks/*
git -C "$root" config core.hooksPath scripts/lead/hooks
echo "hooks: core.hooksPath = scripts/lead/hooks ($(ls "$root/scripts/lead/hooks" | tr '\n' ' '))"
