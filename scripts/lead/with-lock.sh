#!/usr/bin/env bash
# Run a command under a named mutex shared by every lead on this Mac.
#
#   scripts/lead/with-lock.sh <name> [--wait SECONDS | --no-wait] -- <cmd> [args...]
#
# Names: heavy-test (a full local suite, a big render batch, model inference over many
# images), integrate (or any [a-z0-9-]+).
# macOS has no flock(1), so the lock is an atomic `mkdir` of
# .worktrees/.state/locks/<name>.lock holding the holder's pid. A lock whose pid is dead
# (a crashed or killed lead) is broken by the next taker, under a short-lived breaker
# mutex so two waiters can't both break it. Waits forever by default, printing who holds
# it every 30 s. Exits with the command's status; 75 (EX_TEMPFAIL) if the lock wasn't got.
# Sets DMI_LOCK_<NAME>=1 for the command, so a script can re-enter itself under a lock.
#
# heavy-test is machine-wide: this is one Intel Mac, and a big batch here starves studio's
# suites and live app and mir-triage's runs (and theirs starve ours). So that one name is
# taken in studio's lock dir, the same lock studio's and mir-triage's leads take
# ($DMI_SHARED_LOCKS, default ../studio/.worktrees/.state/locks next to the main
# checkout), when that dir exists; without studio it falls back to this repo's own. Every
# other lock is ours. Run what it guards niced: `-- nice -n 15 <cmd>`.
set -euo pipefail
# shellcheck source=scripts/lead/_lib.sh
source "$(dirname "$0")/_lib.sh"

name="${1:-}"
[[ "$name" =~ ^[a-z0-9-]+$ ]] || { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
shift
wait_s=-1
while [ $# -gt 0 ] && [ "$1" != -- ]; do
  case "$1" in
    --wait) wait_s="${2:?}"; shift 2 ;;
    --no-wait) wait_s=0; shift ;;
    *) die "unexpected '$1' (the command goes after --)" ;;
  esac
done
[ "${1:-}" = -- ] || die "missing -- before the command"
shift
[ $# -gt 0 ] || die "no command"

SHARED=" heavy-test "
LOCKS="$STATE/locks"
case "$SHARED" in *" $name "*)
  shared_dir="${DMI_SHARED_LOCKS:-$(dirname "$MAIN")/studio/.worktrees/.state/locks}"
  [ -d "$shared_dir" ] && LOCKS="$shared_dir" ;;
esac
lock="$LOCKS/$name.lock"
mkdir -p "$LOCKS"

mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null || now; }

try_break_stale() {
  local breaker="$lock.break" pid
  if ! mkdir "$breaker" 2>/dev/null; then
    # A breaker that died mid-break leaves its dir behind: clear it after 60 s.
    if [ -d "$breaker" ] && [ $(( $(now) - $(mtime "$breaker") )) -gt 60 ]; then rm -rf "$breaker"; fi
    return 0
  fi
  pid="$(cat "$lock/pid" 2>/dev/null || true)"
  if [ -d "$lock" ]; then
    if [ -n "$pid" ] && ! pid_alive "$pid"; then
      echo "with-lock: breaking stale $name lock (pid $pid is gone)" >&2
      rm -rf "$lock"
    elif [ -z "$pid" ] && [ $(( $(now) - $(mtime "$lock") )) -gt 10 ]; then
      # Taken but no pid: the taker is between mkdir and writing it, or died right there.
      # Only a lock that stays pid-less for 10 s is abandoned.
      echo "with-lock: breaking abandoned $name lock (no pid for 10 s)" >&2
      rm -rf "$lock"
    fi
  fi
  rm -rf "$breaker"
}

start="$(now)"
last_note="$start"
until mkdir "$lock" 2>/dev/null; do
  try_break_stale
  mkdir "$lock" 2>/dev/null && break
  if [ "$wait_s" -ge 0 ] && [ $(( $(now) - start )) -ge "$wait_s" ]; then
    echo "with-lock: $name is held by pid $(cat "$lock/pid" 2>/dev/null || echo '?'): $(cat "$lock/cmd" 2>/dev/null)" >&2
    exit 75
  fi
  if [ $(( $(now) - last_note )) -ge 30 ]; then
    echo "with-lock: waiting for $name (pid $(cat "$lock/pid" 2>/dev/null || echo '?'): $(cat "$lock/cmd" 2>/dev/null))" >&2
    last_note="$(now)"
  fi
  sleep 1
done
echo $$ >"$lock/pid"
now >"$lock/since"
echo "design-manufacture-interface $(session_name): $*" >"$lock/cmd"

release() {
  # Only remove the lock if it's still ours (a breaker could have judged us dead).
  if [ "$(cat "$lock/pid" 2>/dev/null || true)" = $$ ]; then rm -rf "$lock"; fi
}
trap release EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

var="DMI_LOCK_$(echo "$name" | tr 'a-z-' 'A-Z_')"
export "$var=1"
set +e
"$@"
rc=$?
set -e
exit "$rc"
