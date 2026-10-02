#!/usr/bin/env bash
# Proof for the pre-push hook: a throwaway clone pushing to a throwaway bare remote.
# Each refusal (images, a PSD, video, audio, edit projects, ad data, weights, .env*, a
# .pem, a 2 MB blob, Meta and other tokens, a private key) and the allowed cases (a clean branch, .env.example,
# 'allowlist secret', a push to main). It tests the committed state: commit first.
#
#   scripts/lead/tests/test_prepush.sh
set -euo pipefail
SRC="$(cd "$(dirname "$0")/../../.." && pwd)"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/lead-prepush.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
export DMI_TRUNK=main
fails=0
ok() { echo "ok   - $*"; }
bad() { echo "FAIL - $*"; fails=$((fails + 1)); }

git init --quiet --bare "$tmp/remote.git"
git clone --quiet --no-hardlinks "$SRC" "$tmp/clone" 2>/dev/null
c() { git -C "$tmp/clone" "$@"; }
c checkout --quiet -B "$DMI_TRUNK" HEAD 2>/dev/null
c config user.email t@example.invalid; c config user.name "prepush test"
c remote remove origin; c remote add origin "$tmp/remote.git"
# The remote starts with the trunk as it is.
DMI_SKIP_PREPUSH=1 c push --quiet origin "$DMI_TRUNK" 2>/dev/null
"$tmp/clone/scripts/lead/install-hooks.sh" >/dev/null
[ "$(c config core.hooksPath)" = scripts/lead/hooks ] && ok "install-hooks.sh sets core.hooksPath" || bad "hooksPath"

# try <name> <expect: push|refuse> <grep in stderr> -- runs on a fresh branch off the trunk
n=0
try() {
  local name="$1" expect="$2" want="$3"; shift 3
  n=$((n + 1))
  local br="t/$n"
  c checkout --quiet -b "$br" "$DMI_TRUNK"
  "$@" # the commit(s)
  local err rc=0
  err="$(c push --quiet origin "$br" 2>&1)" || rc=$?
  if [ "$expect" = refuse ]; then
    if [ "$rc" != 0 ] && echo "$err" | grep -q "$want"; then ok "refuses $name"; else bad "$name: rc=$rc: $err"; fi
    c ls-remote --exit-code origin "refs/heads/$br" >/dev/null 2>&1 && bad "$name: the branch reached the remote" || true
  else
    if [ "$rc" = 0 ]; then ok "allows $name"; else bad "$name refused: $err"; fi
  fi
  c checkout --quiet "$DMI_TRUNK"
}
add() { # add <path> <content...>
  local p="$tmp/clone/$1"; shift
  mkdir -p "$(dirname "$p")"; printf '%s\n' "$@" >"$p"; c add -f -- "${p#"$tmp/clone/"}"; c commit --quiet -m "add ${p##*/}"
}

try "a clean branch" push "" add scripts/lead/tests/note.txt "harmless"
try "a .psd" refuse "image, design" add designs/breaking-news.psd "8BPS fake"
try "an uppercase .PNG" refuse "image, design" add tests/fixtures/x.PNG "fake"
try "a .jpeg" refuse "image, design" add docs/ad.jpeg "fake"
try "a .webp" refuse "image, design" add out/a.webp "fake"
try "a .tiff" refuse "image, design" add out/a.tiff "fake"
try "a .heic" refuse "image, design" add out/a.heic "fake"
try "an .ai" refuse "image, design" add designs/logo.ai "fake"
try "a .mov" refuse "image, design" add clips/a.mov "fake"
try "an .mp4" refuse "image, design" add clips/haki-ad.mp4 "fake"
try "a .webm" refuse "image, design" add out/v.webm "fake"
try "a .wav" refuse "image, design" add audio/track.wav "fake"
try "an .mp3" refuse "image, design" add audio/track.mp3 "fake"
try "a Premiere project" refuse "image, design" add edits/ad.prproj "fake"
try "an FCPXML" refuse "image, design" add edits/ad.fcpxml "<fcpxml/>"
try "a Resolve project" refuse "image, design" add edits/ad.drp "fake"
try "a Haki deck .pptx" refuse "image, design" add decks/spec.pptx "fake"
try "a .ppt" refuse "image, design" add decks/old.ppt "fake"
try "a BOM .xlsx" refuse "image, design" add exports/bom.xlsx "fake"
try "an artwork .svg" refuse "image, design" add art/logo.svg "<svg/>"
try "a .docx" refuse "image, design" add docs/brief.docx "fake"
try "a pattern .dxf" refuse "image, design" add patterns/brim.dxf "fake"
try "a .zip" refuse "image, design" add exports/pack.zip "fake"
try "a .gif" refuse "image, design" add out/a.gif "fake"
try "an ad export .csv" refuse "image, design" add exports/ads.csv "a,b"
try "a .parquet" refuse "image, design" add data/x.parquet "fake"
try "a .sqlite3" refuse "image, design" add state/runs.sqlite3 "fake"
try "a .db" refuse "image, design" add state/runs.db "fake"
try "model weights" refuse "image, design" add models/u2net.onnx "fake"
try "a .env" refuse ".env/.pem/.key" add .env "META_TOKEN=x"
try "a .env.local" refuse ".env/.pem/.key" add .env.local "META_TOKEN=x"
try "a .env.example" push "" add .env.example "META_TOKEN="
try "a .pem" refuse ".env/.pem/.key" add deploy/cert.pem "-----BEGIN CERTIFICATE-----"
big() { dd if=/dev/urandom of="$tmp/clone/big.bin" bs=1048576 count=2 2>/dev/null; c add -f big.bin; c commit --quiet -m big; }
try "a 2 MB file" refuse "over 1 MB" big
bigthenremoved() { big; c rm --quiet big.bin; c commit --quiet -m "remove big"; }
try "a 2 MB file added then removed" refuse "over 1 MB" bigthenremoved
small() { dd if=/dev/urandom of="$tmp/clone/small.bin" bs=1000 count=900 2>/dev/null; c add -f small.bin; c commit --quiet -m small; }
try "a 0.9 MB file" push "" small
try "a Meta token" refuse "Meta access token" add src/dmi/meta.py 'TOKEN = "EAABsbCS1iHgBAKZBZCfakefakefake0123456789"'  # allowlist secret: test fixture
try "a Meta token in a shell line" refuse "Meta access token" add scripts/run.sh 'curl "https://graph.facebook.com/me?access_token=EAAGm0PX4ZCpsBAFakeFakeFake1234"'  # allowlist secret: test fixture
try "an AWS key" refuse "AWS access key" add src/x.py 'KEY = "AKIAIOSFODNN7EXAMPLE"'  # allowlist secret: test fixture
try "a GitHub token" refuse "GitHub token" add scripts/x.sh 'TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij0123'  # allowlist secret: test fixture
try "a private key" refuse "private key" add deploy/id "-----BEGIN OPENSSH PRIVATE KEY-----" "b3BlbnNzaC1rZXk="  # allowlist secret: test fixture
try "a URL with a password in app code" refuse "URL with a password" add src/settings_local.py 'URL = "postgresql://user:Sup3rS3cretPw@db.example/x"'
try "a URL with a password in a test" push "" add tests/test_x.py 'URL = "postgresql://user:Sup3rS3cretPw@db.example/x"'
try "an allowlisted fake" push "" add src/x.py 'KEY = "AKIAIOSFODNN7EXAMPLE"  # allowlist secret: the AWS docs example'
secret_then_removed() { add src/y.py 'T = "EAABsbCS1iHgBAKZBZCfakefakefake0123456789"'; c rm --quiet src/y.py; c commit --quiet -m rm; }  # allowlist secret: test fixture
try "a secret committed then removed" refuse "Meta access token" secret_then_removed

# main: the lead pushes it, so it is allowed; what it carries is still checked.
c checkout --quiet "$DMI_TRUNK"
echo "# a docs line" >>"$tmp/clone/scripts/lead/tests/note-trunk.txt"; c add -f scripts/lead/tests/note-trunk.txt; c commit --quiet -m "trunk change"
c push --quiet origin "$DMI_TRUNK" 2>/dev/null && ok "allows a push to main" || bad "push to main refused"
c checkout --quiet -b t/x "$DMI_TRUNK"; echo z >"$tmp/clone/z.txt"; c add z.txt; c commit --quiet -m z
c push --quiet origin t/x:main 2>/dev/null && ok "allows branch:main" || bad "branch:main refused"
c checkout --quiet -b t/img "$DMI_TRUNK"; add docs/haki.png "fake"
c push --quiet origin t/img:main 2>/dev/null && bad "an image reached main" || ok "refuses an image pushed to main"
DMI_SKIP_PREPUSH=1 c push --quiet origin t/img 2>/dev/null && ok "DMI_SKIP_PREPUSH=1 bypass works (deliberate)" || bad "skip"

echo
[ "$fails" = 0 ] && echo "all pre-push proofs passed" || { echo "$fails failed"; exit 1; }
