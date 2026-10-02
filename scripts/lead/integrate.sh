#!/usr/bin/env bash
# The integration queue: merge one finished board node into the trunk, one lead at a time,
# under the `integrate` mutex. Run by the lead; nothing else moves the trunk.
#
#   scripts/lead/integrate.sh <node> [--dry-run] [--branch B] [--skip-t0]
#
# Steps (each prints a line; the first failure stops it):
#   1. the node is `review` or `ready` on the board and its branch exists; the main
#      checkout is on the trunk and clean (an uncommitted board edit is allowed: step 6
#      commits the board anyway);
#   2. the trunk is merged into the branch (in the branch's worktree; a conflict aborts
#      the merge and stops here: the node's owner resolves it);
#   3. T0 in the branch's worktree: `uv run ruff check . && uv run ruff format --check . &&
#      uv run pytest -q` once the worktree has a pyproject.toml (until the package exists
#      they are skipped, saying so); plus unittest + bash -n when scripts/lead changed;
#   4. a full-gate node needs the factory-reviewer's PASS marker:
#      .worktrees/.state/pass/<node>, written by the lead, holding the evaluated SHA (the
#      branch tip at evaluation; any later commit must be a merge of the trunk);
#   5. `git merge --no-ff` into the trunk, from the main checkout;
#   6. board: state=merged (committed on the trunk, from the main checkout), the node's
#      claim and PASS marker are released;
#   7. prints what is left for the lead. Nothing is pushed here.
#
# --dry-run does 1, 3 and 4 as they are, tests 2 with `git merge-tree` (touches nothing)
# and only describes 5-7. Rehearse in a throwaway clone (tests/test_integrate.sh), never
# against the real trunk.
set -euo pipefail
# shellcheck source=scripts/lead/_lib.sh
source "$(dirname "$0")/_lib.sh"

node="${1:-}"
[ -n "$node" ] && [ "${node#-}" = "$node" ] || { sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
shift
dry=0 skip_t0=0 branch=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry=1 ;;
    --skip-t0) skip_t0=1 ;;
    --branch) branch="${2:?}"; shift ;;
    *) die "unknown option '$1'" ;;
  esac
  shift
done

# Everything below runs under the integrate mutex.
if [ "${DMI_LOCK_INTEGRATE:-}" != 1 ]; then
  args=("$node")
  [ "$dry" = 1 ] && args+=(--dry-run)
  [ "$skip_t0" = 1 ] && args+=(--skip-t0)
  [ -n "$branch" ] && args+=(--branch "$branch")
  exec "$LEAD_DIR/with-lock.sh" integrate -- "$0" "${args[@]}"
fi

[ -f "$GRAPH" ] || die "no board at $GRAPH (scripts/lead/README.md, 'The board')"
G=("${GRAPH_PY[@]}" --graph "$GRAPH" --state-dir "$STATE")
# The board's path inside the main checkout, when it is the main checkout's (not a test's).
board_rel="${GRAPH#"$MAIN"/}"
[ "$board_rel" != "$GRAPH" ] || board_rel=""
say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
would() { if [ "$dry" = 1 ]; then say "(dry-run) would: $*"; return 0; fi; return 1; }

# ---- 1. the node -------------------------------------------------------------------
step "1. node $node"
state="$("${G[@]}" get "$node" state 2>/dev/null)" || die "unknown node '$node'"
case "$state" in review|ready) ;; *) die "$node is '$state', not review or ready" ;; esac
title="$("${G[@]}" get "$node" title)"
gate="$("${G[@]}" get "$node" gate)"
[ -n "$gate" ] || gate=light
[ -n "$branch" ] || branch="$("${G[@]}" get "$node" branch)"
[ -n "$branch" ] || branch="$(cat "$STATE/claims/$node/branch" 2>/dev/null || true)"
[ -n "$branch" ] || die "$node has no branch (graph.py set $node branch=... or --branch)"
[ "$branch" != "$TRUNK" ] || die "the node's branch is the trunk ($TRUNK)"
git -C "$MAIN" show-ref --verify --quiet "refs/heads/$branch" || die "branch '$branch' doesn't exist"
# What the branch really changed, not what the node declared: the gates follow the diff.
changed="$(git -C "$MAIN" diff --name-only "$TRUNK...$branch")"
touched() { echo "$changed" | grep -q "$1"; }
say "state $state, gate $gate, branch $branch: $title"
[ -n "$changed" ] && say "changes: $(echo "$changed" | tr '\n' ' ')"

# The main checkout: on the trunk and clean, checked now so it fails before any work.
main_branch="$(git -C "$MAIN" symbolic-ref --short HEAD 2>/dev/null || echo DETACHED)"
[ "$main_branch" = "$TRUNK" ] || die "the main checkout $MAIN is on '$main_branch', not $TRUNK"
dirty="$(git -C "$MAIN" status --porcelain --untracked-files=no)"
[ -n "$board_rel" ] && dirty="$(echo "$dirty" | awk -v p="$board_rel" 'substr($0, 4) != p')"
[ -z "$dirty" ] || die "the main checkout has uncommitted changes (only the lead merging writes there):
$dirty"
if [ -n "$board_rel" ] && touched "^$board_rel\$" &&
  [ -n "$(git -C "$MAIN" status --porcelain -- "$board_rel")" ]; then
  die "$branch changes the board and the main checkout has an uncommitted board edit: commit the board first (graph.py set from the main checkout)"
fi

# The branch's worktree: an existing one, or a temporary one that is removed at the end.
wt="$(git -C "$MAIN" worktree list --porcelain | awk -v b="refs/heads/$branch" '
  /^worktree /{w=substr($0,10)} /^branch /{if ($2==b) print w}' | head -1)"
made_wt=0
if [ -z "$wt" ]; then
  wt="$MAIN/.worktrees/$(echo "$branch" | tr '/' '-')"
  if would "add a worktree for $branch at $wt"; then
    wt="$(mktemp -d "${TMPDIR:-/tmp}/integrate-dry.XXXXXX")/wt"
    git -C "$MAIN" worktree add --detach --quiet "$wt" "$branch"
    made_wt=1
  else
    git -C "$MAIN" worktree add --quiet "$wt" "$branch"
    made_wt=1
  fi
fi
cleanup() {
  if [ "$made_wt" = 1 ] && [ -d "$wt" ]; then
    git -C "$MAIN" worktree remove --force "$wt" 2>/dev/null || true
    if [ "$dry" = 1 ]; then rm -rf "$(dirname "$wt")"; fi
  fi
  return 0
}
trap cleanup EXIT
[ -z "$(git -C "$wt" status --porcelain --untracked-files=no)" ] ||
  die "the branch worktree $wt has uncommitted changes; commit them (WIP is fine) first"
tip="$(git -C "$wt" rev-parse HEAD)"
say "worktree $wt at ${tip:0:9}"

# ---- 2. the trunk into the branch --------------------------------------------------------
step "2. merge $TRUNK into $branch"
trunk_sha="$(git -C "$MAIN" rev-parse "$TRUNK")"
if git -C "$MAIN" merge-base --is-ancestor "$TRUNK" "$branch"; then
  say "$TRUNK (${trunk_sha:0:9}) is already in $branch"
elif [ "$dry" = 1 ]; then
  if out="$(git -C "$MAIN" merge-tree --write-tree --name-only "$TRUNK" "$branch" 2>&1)"; then
    say "(dry-run) merge-tree: $TRUNK merges cleanly into $branch"
  else
    say "$out" | sed '1d' | sed 's/^/  /'
    die "$TRUNK conflicts with $branch (above); the node's owner resolves it in $wt"
  fi
else
  if ! git -C "$wt" merge --no-edit -m "Merge $TRUNK into $branch (integrate $node)

$TRAILER" "$TRUNK" >/dev/null 2>&1; then
    git -C "$wt" diff --name-only --diff-filter=U | sed 's/^/  conflict: /'
    git -C "$wt" merge --abort
    die "$TRUNK conflicts with $branch (above); merge aborted. The node's owner resolves it in $wt, then re-run"
  fi
  tip="$(git -C "$wt" rev-parse HEAD)"
  say "merged $TRUNK into $branch -> ${tip:0:9}"
fi

# ---- 2b. no conflict markers ----------------------------------------------------------
step "2b. conflict markers"
if markers="$(git -C "$wt" grep -l -e '^<<<<<<< ' -e '^>>>>>>> ' -- . 2>/dev/null)" && [ -n "$markers" ]; then
  die "conflict markers committed on $branch: $(echo "$markers" | tr '\n' ' ')"
fi
say "none"

# ---- 3. T0 --------------------------------------------------------------------------
step "3. T0"
run() { say "+ $*"; (cd "$wt" && "$@") || die "T0 failed: $*"; }
if [ "$skip_t0" = 1 ]; then
  say "skipped (--skip-t0)"
else
  # The worktree's own venv (uv makes it), never the main checkout's.
  if [ -f "$wt/pyproject.toml" ]; then
    run uv run ruff check .
    run uv run ruff format --check .
    run nice -n 10 uv run pytest -q
  else
    say "no pyproject.toml yet: ruff and pytest skipped (the package doesn't exist)"
  fi
  if touched '^scripts/lead'; then
    run python3 -m unittest discover -q -s scripts/lead/tests -p 'test_*.py'
    for f in "$wt"/scripts/lead/*.sh "$wt"/scripts/lead/hooks/* "$wt"/scripts/lead/tests/*.sh; do
      [ -f "$f" ] && run bash -n "$f"
    done
  fi
fi

# ---- 4. the evaluator gate -------------------------------------------------------------
step "4. factory-reviewer gate"
if [ "$gate" = full ]; then
  marker="$STATE/pass/$node"
  [ -f "$marker" ] || die "full-gate node without a factory-reviewer PASS: write the evaluated SHA to $marker"
  passed="$(tr -d '[:space:]' <"$marker")"
  [[ "$passed" =~ ^[0-9a-f]{7,40}$ ]] || die "the PASS marker $marker must hold the evaluated SHA"
  git -C "$wt" merge-base --is-ancestor "$passed" HEAD 2>/dev/null ||
    die "PASS marker names ${passed:0:9}, which isn't in $branch"
  # Commits after the evaluated SHA must all be merges of the trunk (the evaluator saw the code).
  later="$(git -C "$wt" rev-list --no-merges "$passed..HEAD" "^$TRUNK")"
  [ -z "$later" ] || die "PASS at ${passed:0:9} but $branch has unevaluated commits after it: $(echo "$later" | cut -c1-9 | tr '\n' ' ')"
  say "factory-reviewer PASS at ${passed:0:9} covers the branch"
else
  say "light gate: the lead read the diff and looked at the output"
fi

# ---- 5. merge into the trunk ------------------------------------------------------------
step "5. merge $branch into $TRUNK (--no-ff)"
msg="Merge $branch: $title ($node)

$TRAILER"
if would "git -C $MAIN merge --no-ff $branch  (${tip:0:9} onto ${trunk_sha:0:9})"; then :; else
  git -C "$MAIN" merge --no-ff --no-edit -m "$msg" "$branch" >/dev/null ||
    die "merge into $TRUNK failed (it merged cleanly the other way, so this is unexpected); inspect $MAIN"
  say "$TRUNK is now $(git -C "$MAIN" rev-parse --short HEAD)"
fi

# ---- 6. board and claims ----------------------------------------------------------------
step "6. board: $node -> merged; release the claim"
if would "graph.py set $node state=merged (committed on $TRUNK), claim.sh release $node"; then :; else
  # From the main checkout, so graph.py commits the board on the trunk.
  (cd "$MAIN" && "${G[@]}" set "$node" state=merged >/dev/null)
  "$LEAD_DIR/claim.sh" release "$node" --force >/dev/null || true
  rm -f "$STATE/pass/$node"
  say "board updated, claim released"
fi

# ---- 7. what is left for the lead --------------------------------------------------------
step "7. after the merge (not done here)"
if touched '^pyproject\.toml$\|^uv\.lock$'; then
  say "  dependencies changed: run 'uv sync' in $MAIN and in the worktrees that build on it."
fi
say "  push $TRUNK when ready (the lead pushes; the pre-push hook checks what leaves);"
say "  rebuild the portfolio or contact sheet if this node changes what they show."
if [ "$made_wt" = 1 ] && [ "$dry" = 0 ]; then
  say "  (the temporary worktree $wt is removed; the branch stays)"
elif [ "$dry" = 0 ]; then
  say "  worktree $wt can go: git worktree remove $wt && git branch -d $branch"
fi
if [ "$dry" = 1 ]; then say "
dry-run complete: nothing was merged or written."; fi
exit 0
