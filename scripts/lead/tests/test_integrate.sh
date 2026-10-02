#!/usr/bin/env bash
# Proof for integrate.sh in a throwaway clone (never the real trunk): the board on the
# trunk (graph.py set commits it only from the main checkout), a --dry-run, the refusals
# (wrong state, unknown node, missing branch, dirty main, off the trunk, a failing T0,
# missing or stale PASS, a conflict), then real merges in the clone.
# It tests the committed state of this checkout: commit before running it.
#
#   scripts/lead/tests/test_integrate.sh
set -euo pipefail
SRC="$(cd "$(dirname "$0")/../../.." && pwd)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/lead-integrate.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
unset DMI_LEAD_GRAPH DMI_LOCK_INTEGRATE
export DMI_LEAD_STATE="$tmp/state"
export DMI_LEAD_SESSION=lead-t
export DMI_SHARED_LOCKS="$tmp/shared-locks"
export DMI_TRUNK=trunk-t
export UV_NO_PROGRESS=1
# Until the package exists (no pyproject.toml), T0 is unittest + bash -n and says it skipped
# ruff and pytest; once it exists, these proofs expect ruff, format and pytest too.
has_py=0; [ -f "$SRC/pyproject.toml" ] && has_py=1
fails=0
ok() { echo "ok   - $*"; }
bad() { echo "FAIL - $*"; fails=$((fails + 1)); }
co() { git -C "$tmp/clone" "$@"; }

# A clone whose trunk is this checkout's HEAD (a local clone: no network).
git clone --quiet --no-hardlinks "$SRC" "$tmp/clone" 2>/dev/null
co checkout --quiet -B "$DMI_TRUNK" HEAD 2>/dev/null
co config user.email test@example.invalid; co config user.name "integrate test"
LEAD="$tmp/clone/scripts/lead"
# graph.py from the main checkout (it commits there) and from elsewhere (it doesn't).
gs() { (cd "$tmp/clone" && python3 "$LEAD/graph.py" "$@"); }
gs_away() { (cd "$tmp" && python3 "$LEAD/graph.py" "$@"); }
fixture_node() {
  cat <<EOF
- id: $1
  plan: 0
  spec: []
  title: "a fixture node"
  visible: false
  priority: 10
  user_override: null
  depends_on: []
  touches: []
  agents: []
  checkpoint: false
  state: todo
  branch: null

EOF
}
# The board: on the trunk, in the main checkout, where graph.py looks by default.
{ echo "# a fixture board"; fixture_node node-a; fixture_node node-b; fixture_node node-c; } >"$tmp/clone/claude-plans/graph.yaml"
co commit --quiet -am "a fixture board"
node=node-a

# A finished branch that changes only scripts/lead.
co checkout --quiet -b feat/t "$DMI_TRUNK"
echo "# integrate test" >>"$tmp/clone/scripts/lead/tests/test_claims.sh"
co commit --quiet -am "feat/t: a harmless change"
tip="$(co rev-parse HEAD)"
# A branch outside scripts/lead (docs).
co checkout --quiet -b feat/docs "$DMI_TRUNK"
mkdir -p "$tmp/clone/docs"; echo "# integrate test" >"$tmp/clone/docs/integrate-test.md"
co add docs/integrate-test.md; co commit --quiet -m "feat/docs: a docs change"
# A branch that fails T0 (a shell syntax error in scripts/lead).
co checkout --quiet -b feat/broken "$DMI_TRUNK"
printf 'if then\n' >>"$tmp/clone/scripts/lead/with-lock.sh"
co commit --quiet -am "feat/broken: a syntax error"
co checkout --quiet "$DMI_TRUNK"
# The trunk moves on (a non-conflicting file), so step 2 has something to merge.
echo "# trunk moved" >>"$tmp/clone/scripts/lead/README.md"
co commit --quiet -am "trunk: moved on"

# 0. The board: committed on the trunk from the main checkout, only written from elsewhere.
before="$(co rev-parse "$DMI_TRUNK")"
gs set "$node" state=review branch=feat/t >/dev/null 2>&1
[ "$(co rev-parse "$DMI_TRUNK~1")" = "$before" ] && [ -z "$(co status --porcelain --untracked-files=no)" ] &&
  [ "$(co log -1 --format=%s)" = "Graph: $node state=review branch=feat/t" ] &&
  [ "$(co show --name-only --format= HEAD)" = claude-plans/graph.yaml ] &&
  ok "set from the main checkout commits the board, and only it, on the trunk" ||
  bad "board commit: $(co log -1 --format=%s), status '$(co status --porcelain)'"
before="$(co rev-parse "$DMI_TRUNK")"
out="$(gs_away set node-b state=review branch=feat/docs 2>&1)"
[ "$(co rev-parse "$DMI_TRUNK")" = "$before" ] && [ "$(co status --porcelain --untracked-files=no)" = " M claude-plans/graph.yaml" ] &&
  echo "$out" | grep -q "not committed" && ok "set from elsewhere writes the board, doesn't commit, says so" ||
  bad "set from elsewhere: $out / $(co status --porcelain)"

# 1. dry-run: reports every step, changes nothing. (The uncommitted board edit is allowed.)
before_branch="$(co rev-parse feat/t)"
if out="$("$LEAD/integrate.sh" "$node" --dry-run 2>&1)"; then
  if [ "$has_py" = 1 ]; then
    echo "$out" | grep -q "+ uv run ruff check ." && echo "$out" | grep -q "+ uv run ruff format --check ." &&
      echo "$out" | grep -q "uv run pytest -q" && py_ok=1 || py_ok=0
  else
    echo "$out" | grep -q "no pyproject.toml yet: ruff and pytest skipped" && py_ok=1 || py_ok=0
  fi
  echo "$out" | grep -q "merge-tree: $DMI_TRUNK merges cleanly" && echo "$out" | grep -q "dry-run complete" &&
    [ "$py_ok" = 1 ] && echo "$out" | grep -q "unittest discover" &&
    echo "$out" | grep -q "would: git -C" &&
    ok "dry-run: clean merge-tree, T0 (python: $has_py, unittest) ran, steps 5-7 described" || bad "dry-run output: $out"
else bad "dry-run failed: $out"; fi
[ "$(co rev-parse "$DMI_TRUNK")" = "$before" ] && [ "$(co rev-parse feat/t)" = "$before_branch" ] &&
  [ "$(co worktree list | wc -l | tr -d ' ')" = 1 ] && ok "dry-run changed nothing (trunk, branch, worktrees)" ||
  bad "dry-run changed something"
[ ! -e "$DMI_LEAD_STATE/locks/integrate.lock" ] && ok "integrate lock released" || bad "lock left behind"

# 2. refusals. (This first set, from the main checkout, commits the board edit above too.)
gs set "$node" state=building >/dev/null 2>&1
"$LEAD/integrate.sh" "$node" --dry-run --skip-t0 >/dev/null 2>&1 && bad "building node accepted" || ok "refuses a node that isn't review/ready"
gs set "$node" state=review >/dev/null 2>&1
"$LEAD/integrate.sh" no-such --dry-run >/dev/null 2>&1 && bad "unknown node accepted" || ok "refuses an unknown node"
"$LEAD/integrate.sh" "$node" --dry-run --branch feat/nope >/dev/null 2>&1 && bad "missing branch accepted" || ok "refuses a missing branch"
echo dirty >>"$tmp/clone/CLAUDE.md"
out="$("$LEAD/integrate.sh" "$node" --dry-run --skip-t0 2>&1)" && bad "dirty main accepted" ||
  { echo "$out" | grep -q "CLAUDE.md" && ok "refuses a dirty main checkout (a board edit alone is fine)" || bad "dirty: $out"; }
co checkout --quiet -- CLAUDE.md
co checkout --quiet --detach
out="$("$LEAD/integrate.sh" "$node" --dry-run --skip-t0 2>&1)" && bad "main checkout off the trunk accepted" ||
  { echo "$out" | grep -q "not $DMI_TRUNK" && ok "refuses when the main checkout isn't on the trunk" || bad "off trunk: $out"; }
co checkout --quiet "$DMI_TRUNK"
gs set node-c state=review --no-commit >/dev/null 2>&1
out="$("$LEAD/integrate.sh" node-c --dry-run --branch feat/broken 2>&1)" && bad "failing T0 accepted" ||
  { echo "$out" | grep -q "T0 failed: bash -n" && ok "refuses a branch that fails T0 (bash -n)" || bad "T0: $out"; }
# a full-gate node without the PASS marker, then with a PASS for an older SHA, then a good one
gs set "$node" gate=full >/dev/null 2>&1
out="$("$LEAD/integrate.sh" "$node" --dry-run --skip-t0 2>&1)" && bad "full gate without PASS accepted" ||
  { echo "$out" | grep -q "without a factory-reviewer PASS" && ok "refuses a full-gate node without a factory-reviewer PASS" || bad "no PASS: $out"; }
mkdir -p "$DMI_LEAD_STATE/pass"; co rev-parse "feat/t~1" >"$DMI_LEAD_STATE/pass/$node"
out="$("$LEAD/integrate.sh" "$node" --dry-run --skip-t0 2>&1)" && bad "stale PASS accepted" ||
  { echo "$out" | grep -q "unevaluated commits" && ok "refuses a PASS older than the branch tip" || bad "stale PASS: $out"; }
echo "$tip" >"$DMI_LEAD_STATE/pass/$node"
"$LEAD/integrate.sh" "$node" --dry-run --skip-t0 >/dev/null 2>&1 && ok "accepts a PASS at the branch tip" || bad "good PASS refused"
# a conflict
co checkout --quiet -b feat/conflict "$DMI_TRUNK"
echo "branch side" >"$tmp/clone/scripts/lead/README.md"; co commit --quiet -am "conflict: branch"
co checkout --quiet "$DMI_TRUNK"
echo "trunk side" >"$tmp/clone/scripts/lead/README.md"; co commit --quiet -am "conflict: trunk"
out="$("$LEAD/integrate.sh" "$node" --dry-run --skip-t0 --branch feat/conflict 2>&1)" && bad "conflict accepted" ||
  { echo "$out" | grep -q "conflicts with feat/conflict" && ok "dry-run reports the conflict (merge-tree)" || bad "conflict: $out"; }
out="$("$LEAD/integrate.sh" "$node" --skip-t0 --branch feat/conflict 2>&1)" && bad "real conflict merged" ||
  { echo "$out" | grep -q "merge aborted" && ok "real run aborts the conflicting merge and stops" || bad "conflict real: $out"; }
[ -z "$(co status --porcelain --untracked-files=no)" ] && ok "clone left clean after the aborted merge" || bad "dirty after abort: $(co status --porcelain)"
co worktree prune

# 3. the real thing, in the clone: a full-gate node with its PASS merges, the board says
#    merged (committed on the trunk, the earlier uncommitted edit with it), the claim and
#    the PASS marker go.
"$LEAD/claim.sh" claim "$node" --branch feat/t >/dev/null
gs_away set node-b note=uncommitted >/dev/null 2>&1  # an uncommitted board edit, from elsewhere
out="$("$LEAD/integrate.sh" "$node" 2>&1)" || { bad "integrate failed rc=$?"; echo "$out" | tail -5; }
echo "$out" | grep -q "merged $DMI_TRUNK into feat/t" && ok "step 2: the trunk merged into the branch" || bad "step 2: $out"
echo "$out" | grep -q "unittest discover" && { [ "$has_py" = 0 ] || echo "$out" | grep -q "uv run pytest -q"; } && ok "step 3: T0 ran" || bad "step 3"
echo "$out" | grep -q "PASS at ${tip:0:9} covers the branch" && ok "step 4: the PASS at the evaluated tip covers the trunk merge" || bad "step 4"
co merge-base --is-ancestor feat/t "$DMI_TRUNK" && [ "$(co rev-list --parents -n1 "$DMI_TRUNK~1" | wc -w | tr -d ' ')" = 3 ] &&
  ok "step 5: a --no-ff merge commit on the trunk" || bad "step 5: $(co log --oneline -4 "$DMI_TRUNK")"
[ "$(gs get "$node" state)" = merged ] && [ "$(co log -1 --format=%s)" = "Graph: $node state=merged" ] &&
  [ -z "$(co status --porcelain --untracked-files=no)" ] && [ "$(co show HEAD:claude-plans/graph.yaml | grep -c 'note: uncommitted')" = 1 ] &&
  ok "step 6: board state=merged committed on the trunk (with the earlier uncommitted edit); main clean" ||
  bad "step 6: $(gs get "$node" state), '$(co log -1 --format=%s)', status '$(co status --porcelain)'"
[ ! -e "$DMI_LEAD_STATE/claims/$node" ] && [ ! -e "$DMI_LEAD_STATE/pass/$node" ] && ok "step 6: claim released, PASS marker removed" || bad "claim or marker left"
echo "$out" | grep -q "push $DMI_TRUNK when ready" && ok "step 7: what is left is printed, nothing pushed" || bad "step 7"
[ "$(co worktree list | wc -l | tr -d ' ')" = 1 ] && ok "temporary worktree removed" || bad "worktree left: $(co worktree list)"
# a light-gate change outside scripts/lead, through its T0
out="$("$LEAD/integrate.sh" node-b 2>&1)" && co merge-base --is-ancestor feat/docs "$DMI_TRUNK" &&
  echo "$out" | grep -q "light gate" && [ "$(gs get node-b state)" = merged ] &&
  ok "a light-gate docs change merges after T0" || bad "light merge: $out"

echo
[ "$fails" = 0 ] && echo "all integrate proofs passed" || { echo "$fails failed"; exit 1; }
