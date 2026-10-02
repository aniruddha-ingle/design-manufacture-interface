#!/usr/bin/env bash
# Proofs for claim.sh and with-lock.sh. Uses a throwaway state dir, a throwaway board and a
# throwaway shared-lock dir; never touches the real .worktrees/.state or studio's locks.
#
#   scripts/lead/tests/test_claims.sh
set -euo pipefail
LEAD="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/lead-claims.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
export DMI_LEAD_STATE="$tmp/state"
export DMI_LEAD_GRAPH="$tmp/graph.yaml"
export DMI_SHARED_LOCKS="$tmp/shared-locks"
fails=0
ok() { echo "ok   - $*"; }
bad() { echo "FAIL - $*"; fails=$((fails + 1)); }

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
{ fixture_node node-a; fixture_node node-b; } >"$DMI_LEAD_GRAPH"

# 1. 20 parallel claims on one node: exactly one wins.
node=node-a
for i in $(seq 1 20); do
  ( if DMI_LEAD_SESSION="racer-$i" "$LEAD/claim.sh" claim "$node" >"$tmp/claim.$i.out" 2>&1
    then echo 0 >"$tmp/claim.$i.rc"; else echo 1 >"$tmp/claim.$i.rc"; fi ) &
done
wait
wins=0
for i in $(seq 1 20); do [ "$(cat "$tmp/claim.$i.rc")" = 0 ] && wins=$((wins + 1)); done
holder="$(cat "$DMI_LEAD_STATE/claims/$node/session")"
winner="$(grep -l '^claimed' "$tmp"/claim.*.out | head -1)"
if [ "$wins" = 1 ] && grep -q "as $holder\$" "$winner"; then
  ok "claim race: 20 parallel claims, exactly 1 won ($holder)"
else
  bad "claim race: $wins winners"
fi
if DMI_LEAD_SESSION=other "$LEAD/claim.sh" release "$node" 2>/dev/null; then
  bad "release by another session should refuse"
else ok "release by another session refused"; fi
DMI_LEAD_SESSION="$holder" "$LEAD/claim.sh" release "$node" >/dev/null
[ ! -e "$DMI_LEAD_STATE/claims/$node" ] && ok "holder released it" || bad "release"
"$LEAD/claim.sh" claim no-such-node 2>/dev/null && bad "unknown node claimed" || ok "unknown node refused"

# 2. 10 parallel claim-number calls: 10 distinct numbers, above every step plan in use
#    (09a-/09b- count as 09).
for i in $(seq 1 10); do "$LEAD/claim.sh" claim-number plan >"$tmp/num.$i" & done
wait
distinct="$(cat "$tmp"/num.* | sort -u | wc -l | tr -d ' ')"
lowest="$(cat "$tmp"/num.* | sort | head -1)"
in_use="$(ls "$LEAD/../../claude-plans" | sed -n 's/^\([0-9]\{2\}\)[a-z]\{0,1\}-.*/\1/p' | sort | tail -1)"
if [ "$distinct" = 10 ] && [ "$((10#$lowest))" -gt "$((10#$in_use))" ]; then
  ok "claim-number race: 10 distinct plan numbers from $lowest (highest on disk here $in_use)"
else
  bad "claim-number: $distinct distinct, lowest $lowest, in use $in_use"
fi
[ "$("$LEAD/claim.sh" claim-number lead)" = lead-1 ] && [ "$("$LEAD/claim.sh" claim-number lead)" = lead-2 ] &&
  ok "lead numbers lead-1, lead-2" || bad "lead numbers"
"$LEAD/claim.sh" claim-number adr >/dev/null 2>&1 && bad "unknown kind accepted" || ok "unknown number kind refused"

# 3. The mutex: 10 parallel read-sleep-write increments under with-lock lose nothing.
echo 0 >"$tmp/counter"
for i in $(seq 1 10); do
  "$LEAD/with-lock.sh" integrate -- bash -c 'n=$(cat "$1"); sleep 0.2; echo $((n + 1)) >"$1"' _ "$tmp/counter" &
done
wait
[ "$(cat "$tmp/counter")" = 10 ] && ok "with-lock: 10 parallel increments, counter = 10" ||
  bad "with-lock: counter = $(cat "$tmp/counter") (lost updates)"

# 4. A lock left by a dead pid is broken by the next taker; a live one is not.
bash -c 'exit 0' & dead=$!; wait "$dead"
mkdir -p "$DMI_LEAD_STATE/locks/other.lock" && echo "$dead" >"$DMI_LEAD_STATE/locks/other.lock/pid"
out="$("$LEAD/with-lock.sh" other --wait 5 -- echo ran 2>&1)" && echo "$out" | grep -q "breaking stale" &&
  echo "$out" | grep -q '^ran$' && ok "stale lock (dead pid $dead) broken, command ran" ||
  bad "stale lock: $out"
sleep 30 & live=$!
disown "$live" 2>/dev/null || true
mkdir -p "$DMI_LEAD_STATE/locks/other.lock" && echo "$live" >"$DMI_LEAD_STATE/locks/other.lock/pid"
set +e
"$LEAD/with-lock.sh" other --no-wait -- echo ran >/dev/null 2>&1
rc=$?
set -e
kill "$live" 2>/dev/null || true
[ "$rc" = 75 ] && ok "live lock respected (exit 75)" || bad "live lock: rc $rc"
rm -rf "$DMI_LEAD_STATE/locks/other.lock"

# 5. The command's exit status comes through, the lock is released, and re-entry is flagged.
set +e
"$LEAD/with-lock.sh" integrate -- bash -c 'exit 7'
rc=$?
set -e
[ "$rc" = 7 ] && [ ! -e "$DMI_LEAD_STATE/locks/integrate.lock" ] && ok "exit status 7 passed through, lock released" ||
  bad "exit status $rc"
[ "$("$LEAD/with-lock.sh" integrate -- bash -c 'echo "$DMI_LOCK_INTEGRATE"')" = 1 ] &&
  ok "DMI_LOCK_INTEGRATE=1 inside" || bad "lock env var"

# 6. heavy-test is the machine-wide lock: taken in the shared dir when it exists (studio's),
#    in our own state dir when it doesn't; every other name is always ours.
mkdir -p "$DMI_SHARED_LOCKS"
where="$("$LEAD/with-lock.sh" heavy-test -- bash -c 'ls -d "$1"/heavy-test.lock "$2"/heavy-test.lock 2>/dev/null || true' _ "$DMI_SHARED_LOCKS" "$DMI_LEAD_STATE/locks")"
[ "$where" = "$DMI_SHARED_LOCKS/heavy-test.lock" ] && ok "heavy-test is held in the shared lock dir" || bad "heavy-test lock at: $where"
sleep 30 & live=$!
disown "$live" 2>/dev/null || true
mkdir -p "$DMI_SHARED_LOCKS/heavy-test.lock" && echo "$live" >"$DMI_SHARED_LOCKS/heavy-test.lock/pid"
echo "studio lead-1: pytest" >"$DMI_SHARED_LOCKS/heavy-test.lock/cmd"
set +e
"$LEAD/with-lock.sh" heavy-test --no-wait -- echo ran >/dev/null 2>&1
rc=$?
set -e
[ "$rc" = 75 ] && ok "a heavy-test lock held by studio is respected (exit 75)" || bad "shared lock ignored: rc $rc"
locks="$("$LEAD/claim.sh" locks)"
grep -q 'mutex   heavy-test' <<<"$locks" && ok "locks lists the shared heavy-test lock" || bad "locks: $locks"
kill "$live" 2>/dev/null || true
rm -rf "$DMI_SHARED_LOCKS"
where="$("$LEAD/with-lock.sh" heavy-test -- bash -c 'ls -d "$1"/heavy-test.lock 2>/dev/null || true' _ "$DMI_LEAD_STATE/locks")"
[ "$where" = "$DMI_LEAD_STATE/locks/heavy-test.lock" ] && ok "without a shared dir, heavy-test falls back to our own" || bad "fallback: $where"

# 6b. Without the override, heavy-test resolves to studio's lock dir next to this repo, the
#     one studio's and mir-triage's leads take (read-only check: nothing is locked there).
default_shared="$(unset DMI_SHARED_LOCKS; bash -c 'source "$1/_lib.sh"; echo "$(dirname "$MAIN")/studio/.worktrees/.state/locks"' _ "$LEAD")"
grep -q 'shared_dir="${DMI_SHARED_LOCKS:-$(dirname "$MAIN")/studio/.worktrees/.state/locks}"' "$LEAD/with-lock.sh" &&
  ok "heavy-test's default dir is $default_shared$([ -d "$default_shared" ] || echo ' (absent here: falls back to ours)')" ||
  bad "with-lock.sh's shared dir default changed"

# 7. locks and stale report.
DMI_LEAD_SESSION=lead-9 "$LEAD/claim.sh" claim node-b --branch no/such-branch >/dev/null
echo $(( $(date +%s) - 13 * 3600 )) >"$DMI_LEAD_STATE/claims/node-b/since"
# (Output captured first: `grep -q` closing the pipe early would fail it under pipefail.)
locks="$("$LEAD/claim.sh" locks)"
grep -q 'claim   node-b' <<<"$locks" && ok "locks lists the claim" || bad "locks: $locks"
stale="$("$LEAD/claim.sh" stale)"
grep -q '^stale: node-b (lead-9)' <<<"$stale" && ok "13 h idle claim reported stale" || bad "stale: $stale"
[ -e "$DMI_LEAD_STATE/claims/node-b" ] && ok "stale claim reported, not broken" || bad "stale claim was broken"

echo
[ "$fails" = 0 ] && echo "all claim/lock proofs passed" || { echo "$fails failed"; exit 1; }
