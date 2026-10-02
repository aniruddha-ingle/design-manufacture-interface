# shellcheck shell=bash
# Shared helpers for scripts/lead/*.sh (claude-plans/00-organisation.md). Sourced, never
# run. Bash 3.2 (macOS).
#
# LEAD_DIR   this directory
# MAIN       the main checkout (the parent of the shared .git), from any worktree. Nothing
#            runs it in production, so the board lives there, on the trunk
# GRAPH      the board: $DMI_LEAD_GRAPH, or $MAIN/claude-plans/graph.yaml
# STATE      $DMI_LEAD_STATE, or $MAIN/.worktrees/.state (gitignored with .worktrees/)
# TRAILER    the Co-Authored-By line for the commits integrate.sh makes; a session on
#            another model sets $DMI_COMMIT_TRAILER
# TRUNK      the trunk branch. This is the ONE place it is named: change the default here
#            when the trunk is renamed ($DMI_TRUNK overrides it, for the proofs;
#            graph.py reads the same variable)

LEAD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_common="$(git -C "$LEAD_DIR" rev-parse --path-format=absolute --git-common-dir)"
MAIN="$(dirname "$_common")"
unset _common
STATE="${DMI_LEAD_STATE:-$MAIN/.worktrees/.state}"
TRUNK="${DMI_TRUNK:-main}"
export DMI_TRUNK="$TRUNK"
GRAPH="${DMI_LEAD_GRAPH:-$MAIN/claude-plans/graph.yaml}"
TRAILER="${DMI_COMMIT_TRAILER:-Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>}"
GRAPH_PY=(python3 "$LEAD_DIR/graph.py")

die() { echo "error: $*" >&2; exit 1; }
now() { date +%s; }
iso() { date -u -r "${1:-$(now)}" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d "@${1:-$(now)}" +%Y-%m-%dT%H:%M:%SZ; }
age_h() { echo $(( ( $(now) - $1 ) / 3600 )); }
pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }
session_name() { echo "${DMI_LEAD_SESSION:-unnamed}"; }
