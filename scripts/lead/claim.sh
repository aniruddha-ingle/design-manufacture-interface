#!/usr/bin/env bash
# Claims and numbers for parallel leads on this Mac. Atomic `mkdir` under
# .worktrees/.state/ (gitignored): the first mkdir wins, everyone else sees it exists.
#
#   claim.sh claim <node> [--branch B]     claim a board node
#   claim.sh release <node> [--force]      release it (--force: someone else's)
#   claim.sh claim-number plan|lead        the next free number, reserved atomically
#   claim.sh release-number <kind> <n>     give a number back (e.g. a lead that ends)
#   claim.sh locks                         claims, numbers and mutexes held now
#   claim.sh stale [--hours H]             claims idle over H hours (default 12); report only
#
# The session is $DMI_LEAD_SESSION (e.g. lead-1, from `claim-number lead`).
# $DMI_LEAD_STATE overrides the state dir, $DMI_LEAD_GRAPH the board (tests).
# Stale claims are reported, never broken: a lead or the user releases them.
set -euo pipefail
# shellcheck source=scripts/lead/_lib.sh
source "$(dirname "$0")/_lib.sh"

CLAIMS="$STATE/claims"
RES="$STATE/resources"
SPECIAL_CLAIMS=" "  # claims that aren't board nodes (none yet)

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

node_exists() {
  case "$SPECIAL_CLAIMS" in *" $1 "*) return 0 ;; esac
  "${GRAPH_PY[@]}" --graph "$GRAPH" get "$1" state >/dev/null 2>&1
}

cmd_claim() {
  local node="${1:-}" branch=""
  [ -n "$node" ] || usage
  shift
  while [ $# -gt 0 ]; do
    case "$1" in
      --branch) branch="${2:?}"; shift 2 ;;
      *) usage ;;
    esac
  done
  node_exists "$node" || die "unknown node '$node' (not in the graph)"
  mkdir -p "$CLAIMS"
  if mkdir "$CLAIMS/$node" 2>/dev/null; then
    session_name >"$CLAIMS/$node/session"
    now >"$CLAIMS/$node/since"
    echo "$branch" >"$CLAIMS/$node/branch"
    echo "claimed $node as $(session_name)"
    return 0
  fi
  local who
  who="$(cat "$CLAIMS/$node/session" 2>/dev/null || echo '?')"
  echo "already claimed: $node by $who" >&2
  return 1
}

cmd_release() {
  local node="${1:-}" force="${2:-}"
  [ -n "$node" ] || usage
  [ -d "$CLAIMS/$node" ] || { echo "not claimed: $node"; return 0; }
  local who me
  who="$(cat "$CLAIMS/$node/session" 2>/dev/null || echo unnamed)"
  me="$(session_name)"
  if [ "$force" != "--force" ] && [ "$who" != unnamed ] && [ "$me" != unnamed ] && [ "$who" != "$me" ]; then
    die "$node is claimed by $who, not $me (pass --force to release it anyway)"
  fi
  rm -f "$CLAIMS/$node/session" "$CLAIMS/$node/since" "$CLAIMS/$node/branch"
  rmdir "$CLAIMS/$node"
  echo "released $node"
}

# kind -> "dir regex width"
kind_spec() {
  case "$1" in
    # Steps are NN-name.md, with a letter for a split step (09a-, 09b-).
    plan) echo "claude-plans ^([0-9]{2})[a-z]?- 2" ;;
    lead) echo "- - 0" ;;
    *) die "unknown kind '$1' (plan|lead)" ;;
  esac
}

# Highest number in use for a kind: every local branch, every worktree's files on disk
# (uncommitted work too), and every reserved number.
max_in_use() {
  local kind="$1" dir re width max=0 n names
  read -r dir re width <<<"$(kind_spec "$kind")"
  if [ "$dir" != - ]; then
    names="$(
      git -C "$MAIN" for-each-ref --format='%(refname:short)' refs/heads |
        while IFS= read -r b; do git -C "$MAIN" ls-tree --name-only "$b" "$dir/" 2>/dev/null; done
      git -C "$MAIN" worktree list --porcelain | sed -n 's/^worktree //p' |
        while IFS= read -r wt; do [ -d "$wt/$dir" ] && ls "$wt/$dir"; done
    )"
    while IFS= read -r f; do
      f="${f##*/}"
      if [[ "$f" =~ $re ]]; then
        n=$((10#${BASH_REMATCH[1]}))
        [ "$n" -gt "$max" ] && max=$n
      fi
    done <<<"$names"
  fi
  if [ -d "$RES" ]; then
    for d in "$RES/$kind"-*; do
      [ -d "$d" ] || continue
      n="${d##*-}"
      [[ "$n" =~ ^[0-9]+$ ]] && [ "$((10#$n))" -gt "$max" ] && max=$((10#$n))
    done
  fi
  echo "$max"
}

cmd_claim_number() {
  local kind="${1:-}" dir re width n
  [ -n "$kind" ] || usage
  kind_spec "$kind" >/dev/null # an unknown kind dies here, not inside the $(...) below
  read -r dir re width <<<"$(kind_spec "$kind")"
  mkdir -p "$RES"
  n=$(( $(max_in_use "$kind") + 1 ))
  until mkdir "$RES/$kind-$n" 2>/dev/null; do n=$((n + 1)); done
  session_name >"$RES/$kind-$n/session"
  now >"$RES/$kind-$n/since"
  if [ "$kind" = lead ]; then echo "lead-$n"; else printf "%0${width}d\n" "$n"; fi
}

cmd_release_number() {
  local kind="${1:-}" n="${2:-}"
  [ -n "$kind" ] && [ -n "$n" ] || usage
  kind_spec "$kind" >/dev/null
  n="${n#lead-}"
  n=$((10#$n))
  local d="$RES/$kind-$n"
  [ -d "$d" ] || { echo "not reserved: $kind $n"; return 0; }
  rm -f "$d/session" "$d/since"
  rmdir "$d"
  echo "released $kind $n"
}

last_commit() { git -C "$MAIN" log -1 --format=%ct "$1" -- 2>/dev/null || echo 0; }

cmd_locks() {
  local any=0 d since
  echo "state: $STATE"
  for d in "$CLAIMS"/*; do
    [ -d "$d" ] || continue
    any=1
    since="$(cat "$d/since" 2>/dev/null || echo 0)"
    printf 'claim   %-28s %-10s since %s (%sh)  branch %s\n' "${d##*/}" \
      "$(cat "$d/session" 2>/dev/null)" "$(iso "$since")" "$(age_h "$since")" \
      "$(cat "$d/branch" 2>/dev/null)"
  done
  for d in "$RES"/*; do
    [ -d "$d" ] || continue
    any=1
    since="$(cat "$d/since" 2>/dev/null || echo 0)"
    printf 'number  %-28s %-10s since %s\n' "${d##*/}" "$(cat "$d/session" 2>/dev/null)" "$(iso "$since")"
  done
  # Our own mutexes, and the machine-wide heavy-test lock in studio's dir (with-lock.sh).
  local shared="${DMI_SHARED_LOCKS:-$(dirname "$MAIN")/studio/.worktrees/.state/locks}"
  for d in "$STATE/locks"/*.lock "$shared/heavy-test.lock"; do
    [ -d "$d" ] || continue
    any=1
    local pid state=alive
    pid="$(cat "$d/pid" 2>/dev/null || true)"
    pid_alive "$pid" || state="DEAD (the next taker breaks it)"
    printf 'mutex   %-28s pid %s %s: %s\n' "$(basename "$d" .lock)" "$pid" "$state" "$(cat "$d/cmd" 2>/dev/null)"
  done
  [ "$any" = 1 ] || echo "nothing held"
}

cmd_stale() {
  local hours=12 d since branch last activity limit n=0 node
  [ "${1:-}" = --hours ] && hours="${2:?}"
  for d in "$CLAIMS"/*; do
    [ -d "$d" ] || continue
    node="${d##*/}"
    since="$(cat "$d/since" 2>/dev/null || echo 0)"
    branch="$(cat "$d/branch" 2>/dev/null || true)"
    limit=$((hours * 3600))
    case "$SPECIAL_CLAIMS" in *" $node "*) limit=$((24 * 3600)); branch="" ;; esac
    activity="$since"
    if [ -n "$branch" ]; then
      last="$(last_commit "$branch")"
      [ "${last:-0}" -gt "$activity" ] && activity="$last"
    fi
    if [ $(( $(now) - activity )) -gt "$limit" ]; then
      n=$((n + 1))
      echo "stale: $node ($(cat "$d/session" 2>/dev/null)), claimed $(iso "$since"), last activity $(iso "$activity")${branch:+ on $branch}"
    fi
  done
  [ "$n" = 0 ] && echo "no stale claims (over ${hours} h idle)"
  return 0
}

case "${1:-}" in
  claim) shift; cmd_claim "$@" ;;
  release) shift; cmd_release "$@" ;;
  claim-number) shift; cmd_claim_number "$@" ;;
  release-number) shift; cmd_release_number "$@" ;;
  locks) cmd_locks ;;
  stale) shift; cmd_stale "$@" ;;
  *) usage ;;
esac
