# scripts/lead: the lead's tooling

Ported from product-in-video's `scripts/lead` (itself from copy-in-product-picture's,
mir-triage's and studio's) on 2026-10-02, when the department was set up (record:
[`claude-plans/00-organisation.md`](../../claude-plans/00-organisation.md)). Changes: the
`DMI_` prefix, the factory-reviewer gate, and slide decks, documents, spreadsheets, vector
artwork, CAD patterns and archives added to the pre-push refusals (Haki's tech packs).
Everything here is stdlib Python 3.10+ and bash 3.2 (macOS), no installs, so it runs with
the system `python3` and never touches a venv. The scripts find the main checkout through
the shared `.git`, so they work from any worktree.

| Tool | Does |
|---|---|
| `graph.py` | The board, `claude-plans/graph.yaml` on the trunk: `check`, `ready`, `pick`, `show`, `get`, `set` |
| `claim.sh` | Atomic claims on nodes and numbers (plan, lead) under `.worktrees/.state/` |
| `with-lock.sh` | A named mutex: `heavy-test` (machine-wide, shared with studio, mir-triage and copy-in-product-picture), `integrate` |
| `integrate.sh` | The integration queue: one finished node into the trunk, gates enforced |
| `hooks/pre-push`, `install-hooks.sh` | The last check before anything leaves the Mac |
| `_lib.sh` | Shared helpers. **`TRUNK` (`main`) is named here and nowhere else** |
| `tests/` | `test_graph.py` (unittest) and the bash proofs, each in a throwaway clone or state dir |

There is no `release.sh`: nothing runs a release checkout of this repo.

## The board: `graph.yaml`

One entry per buildable node: `id` (stable), `plan` (the step number), `spec` (`[]`),
`title`, `visible` (the user or Devin will see it: it leads), `priority` (lower first),
`user_override` (set only when the user says so; always wins), `depends_on`, `touches`
(globs), `agents`, `checkpoint` (stop for the user before merging), `state`, `branch`,
`gate` (`light` | `full`), and optionally `blocked` (why a todo isn't ready), `note`.

States: `todo → claimed → building → built → review → ready → merged`, or `dropped`.
`built` = the gates are green in the node's worktree and the builder's report is checked.
`merged` = on the trunk.

The file is a strict YAML subset the stdlib parses: a list of flat mappings, one-line
`[flow, lists]`, JSON-style quoting for anything with `*`, `:`, `#` or `|`. `graph.py set`
edits lines in place, so comments survive. `graph.py check` refuses cycles, unknown ids
and states, and warns about running nodes whose `touches` overlap.

```bash
python3 scripts/lead/graph.py check
python3 scripts/lead/graph.py show                       # the table, for the user
python3 scripts/lead/graph.py ready -v                   # what may start, and why the rest can't
python3 scripts/lead/graph.py pick --random-ties         # the next node; ties: random, logged
```

`ready` order: `user_override`, then `visible`, then `priority`, then `plan`. A node is
held while it is `blocked`, while a dependency isn't merged, while a running (claimed,
building, built, review, ready) node's `touches` overlap its own, or while a higher-ranked
ready node overlaps it, so **two overlapping nodes are never both ready**. A tie at the
top is broken at random (`tiebreak: random` on the node, a line in
`.worktrees/.state/tiebreaks.log`).

**The board lives on the trunk**, at `claude-plans/graph.yaml` in the main checkout:
nothing runs that checkout in production (unlike mir-triage, whose checkout studio ran),
so a board commit there disturbs nobody. `graph.py` reads the main checkout's file from
any worktree. `graph.py set` (and a logged `pick --random-ties`) commits that one file on
the trunk **only when run from the main checkout while it is on `main`**; from a worktree
it writes the file, leaves it uncommitted and prints a note saying so (as `--no-commit`
does). Builders don't edit the board: they report, and the lead sets states from the main
checkout.

```bash
python3 scripts/lead/graph.py set p1-timeline-format state=review   # from the main checkout: one commit on main
git log --oneline -5 -- claude-plans/graph.yaml               # the board's history
```

If the board ever has to leave the trunk (something starts running the main checkout),
mir-triage's port shows how: an orphan `board` branch in `.worktrees/board`.

## Claims and locks: `claim.sh`, `with-lock.sh`

```bash
export DMI_LEAD_SESSION="$(scripts/lead/claim.sh claim-number lead)"   # lead-1, lead-2, ...
scripts/lead/claim.sh claim p1-timeline-format --branch p1-timeline-format   # first mkdir wins
scripts/lead/claim.sh claim-number plan      # 02: the next step number
scripts/lead/claim.sh locks                  # who holds what, here and the shared heavy-test
scripts/lead/claim.sh stale                  # > 12 h, no commits: reported, never broken
scripts/lead/claim.sh release p1-timeline-format
scripts/lead/with-lock.sh heavy-test -- nice -n 15 <decode / track / render batch>
```

- A shell's environment doesn't persist between tool calls: put
  `DMI_LEAD_SESSION=lead-N` in the same command as any claim.
- Claims are directories under `.worktrees/.state/claims/<node>/` (`session`, `since`,
  `branch`); `.worktrees/` is gitignored. A claimed node counts as running for
  `graph.py ready`, even before its state is set.
- `claim-number plan` scans every local branch, every worktree on disk (uncommitted files
  too) and the reservations, then reserves `max + 1` atomically. Split steps (`09a-`,
  `09b-`) count as their number.
- `with-lock.sh` is an atomic `mkdir` with a pid file (macOS has no `flock`). A lock whose
  pid is dead is broken by the next taker; a live one is waited for (`--wait N` or
  `--no-wait` → exit 75). The command sees `DMI_LOCK_<NAME>=1`.
- **`heavy-test` is machine-wide**, the same lock studio's, mir-triage's and
  copy-in-product-picture's leads take: `../studio/.worktrees/.state/locks/heavy-test.lock`
  (studio's gitignored state). This is one Intel Mac with no GPU: a full suite or a
  batch render of many packages here starves studio's live app and the other repos' runs.
  Take it for all of those, run them `nice -n 15`, and cap threads (
  `OMP_NUM_THREADS`). Without studio's directory it falls back to this repo's own.

Proofs: `tests/test_claims.sh` (20 parallel claims → exactly 1 winner; 10 parallel numbers
→ 10 distinct; 10 locked increments lose nothing; dead-pid locks broken, live ones
respected; `heavy-test` lands in the shared dir and respects a lock studio holds; its
default dir is studio's).

## Integration: `integrate.sh`

```bash
scripts/lead/integrate.sh p1-timeline-format --dry-run           # rehearse: merge-tree, T0, the PASS marker
echo <evaluated sha> > .worktrees/.state/pass/p1-timeline-format # the lead, after factory-reviewer's PASS
scripts/lead/integrate.sh p1-timeline-format
```

The lead runs it; nothing else moves the trunk. Under the `integrate` mutex: (1) the node
is `review` or `ready` and its branch exists, and the main checkout is on `main` and clean
(an uncommitted board edit is allowed; step 6 commits it); (2) the trunk is merged into
the branch, in the branch's worktree (a conflict aborts and stops: the owner resolves
it); (3) T0 in that worktree: `uv run ruff check . && uv run ruff format --check . &&
uv run pytest -q` once it has a `pyproject.toml` (skipped, saying so, until the package
exists), plus unittest and `bash -n` when `scripts/lead` changed; (4) a
`gate: full` node needs the **factory-reviewer PASS** marker
`.worktrees/.state/pass/<node>` holding the evaluated SHA, and every later commit on the
branch must be a merge of the trunk; (5) `git merge --no-ff` into `main`; (6) the board
says `merged` (committed on `main` from the main checkout), the claim and the PASS
marker go; (7) what is left for the lead is printed. Nothing is pushed here: the lead
pushes `main` afterwards (the pre-push hook checks what leaves). Proof:
`tests/test_integrate.sh`, in a throwaway clone.

## Before anything leaves the Mac: the pre-push hook

`scripts/lead/install-hooks.sh` sets `core.hooksPath = scripts/lead/hooks` (one setting for
every worktree, under version control; `--uninstall` removes it). The hook refuses a push
whose commits contain:

- an image, design, deck, document or data file: `*.psd *.psb *.ai *.eps *.pdf *.png
  *.jpg *.jpeg *.webp *.gif *.tif* *.heic *.svg`, `*.pptx *.ppt *.potx *.odp *.docx *.doc
  *.pages *.xlsx *.xls *.numbers *.csv`, `*.dxf *.dwg`, `*.zip`, video, audio and edit
  projects, `*.parquet *.sqlite* *.db *.dump`, and model weights (Haki's decks, artwork,
  measurements and supplier data never go in git; tests make synthetic products and decks
  at run time);
- a `.env*` file (only `.env.example` is allowed), a `.pem` or `.key` file;
- a blob over 1 MB (even one added and removed again in the pushed commits);
- an added line shaped like a secret: private keys, **Meta tokens** (`EAA…`), GitHub, AWS,
  Anthropic/OpenAI, Slack, JWTs, and in non-test code a URL with a password or an
  assigned secret. A known fake carries `allowlist secret` on its line.

A push to `main` is allowed (the lead pushes it); what it carries is checked like any
other. Proof: `tests/test_prepush.sh`, against a throwaway bare remote.

## Running the proofs

They test the **committed** state of the checkout they sit in (they clone it), touch
nothing outside a temp dir, and take about a minute together:

```bash
python3 -m unittest discover -q -s scripts/lead/tests -p 'test_*.py'
scripts/lead/tests/test_claims.sh
scripts/lead/tests/test_integrate.sh
scripts/lead/tests/test_prepush.sh
```

## Environment

| Variable | Meaning |
|---|---|
| `DMI_LEAD_SESSION` | this session's name (`lead-N`) on claims and locks |
| `DMI_TRUNK` | overrides `TRUNK` from `_lib.sh` (the proofs use it) |
| `DMI_LEAD_STATE`, `DMI_LEAD_GRAPH`, `DMI_SHARED_LOCKS` | other state dir, board file, shared-lock dir (the proofs) |
| `DMI_COMMIT_TRAILER` | the Co-Authored-By line on `integrate.sh`'s and `graph.py`'s commits |
| `DMI_SKIP_PREPUSH=1` | skip the hook (deliberate; say so) |
