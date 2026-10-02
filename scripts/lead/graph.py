"""The board, `claude-plans/graph.yaml` on the trunk (claude-plans/00-organisation.md;
ported from copy-in-product-picture's scripts/lead, via mir-triage's, from studio's). Stdlib only, Python 3.10+.

    python3 scripts/lead/graph.py check                 # shape, ids, states, deps, cycles
    python3 scripts/lead/graph.py ready                 # what a lead may start now, in order
    python3 scripts/lead/graph.py pick [--random-ties] [--seed N] [--no-log]
    python3 scripts/lead/graph.py show                  # a table for the user
    python3 scripts/lead/graph.py get <id> [field]      # one node (JSON) or one field
    python3 scripts/lead/graph.py set <id> key=value [key=value ...]

The board lives on the trunk, in the main checkout: nothing runs that checkout in
production, so a board commit there disturbs nobody. From any worktree, graph.py reads
<main checkout>/claude-plans/graph.yaml. `set` (and a logged `pick --random-ties`) edits
it in place and commits that one file, on the trunk, only when run from the main checkout
while it is on the trunk ($DMI_TRUNK, default main). From anywhere else the file is
written and left uncommitted, with a note saying so (as with `--no-commit`).

`--graph PATH` reads another file (default: $DMI_LEAD_GRAPH, or the main checkout's).
`--state-dir DIR` is where claims live (default: <main checkout>/.worktrees/.state, or
$DMI_LEAD_STATE); a claimed node counts as running even before its state is set.

The file is a strict YAML subset, parsed here without PyYAML (the system `python3` runs
this, outside any venv): a top-level list of flat mappings whose values are null,
true/false, integers, strings (plain or JSON-quoted) or one-line [flow, lists] of those.
Every file in that subset is also valid YAML 1.2, so any YAML tool can read it. `set`
edits lines in place, so comments survive.

States: todo -> claimed -> building -> built -> review -> ready -> merged (or dropped).
`built` = the gates are green in the node's worktree and the builder's report is checked.
`merged` = on the trunk.

Ranking: user_override (set, low first) > visible > priority (low first) > plan. A todo
node is ready when it isn't blocked, every dependency is merged, and its `touches`
overlap no running node (claimed, building, built, review, ready) and no higher-ranked
ready node. Equal rank is a tie: `pick --random-ties` chooses at random and logs
`tiebreak: random` on the node.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import subprocess
import sys
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"  # or $DMI_COMMIT_TRAILER

STATES = (
    "todo", "claimed", "building", "built", "review", "ready", "merged", "dropped",
)  # fmt: skip
RUNNING = frozenset({"claimed", "building", "built", "review", "ready"})
DONE = frozenset({"merged"})
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# field -> (types, required)
FIELDS: dict[str, tuple[tuple[type, ...], bool]] = {
    "id": ((str,), True),
    "plan": ((int,), True),
    "spec": ((list,), True),
    "title": ((str,), True),
    "visible": ((bool,), True),
    "priority": ((int,), True),
    "user_override": ((int, type(None)), True),
    "depends_on": ((list,), True),
    "touches": ((list,), True),
    "agents": ((list,), True),
    "checkpoint": ((bool,), True),
    "state": ((str,), True),
    "branch": ((str, type(None)), True),
    "blocked": ((str, type(None)), False),
    "tiebreak": ((str, type(None)), False),
    "tiebreak_among": ((list,), False),
    "note": ((str, type(None)), False),
    "gate": ((str,), False),
}
GATES = ("light", "full")


class GraphError(Exception):
    pass


# ---------------------------------------------------------------- the YAML subset

PLAIN_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./+-]*$")
INT_RE = re.compile(r"^-?[0-9]+$")
KEY_RE = re.compile(r"^([a-z_][a-z0-9_]*):(?:\s+(.*))?$")


def _strip_comment(s: str) -> str:
    """Drop a trailing `# comment` that sits outside quotes (YAML: `#` after a space)."""
    quote = None
    esc = False
    for i, ch in enumerate(s):
        if quote:
            if esc:
                esc = False
            elif ch == "\\" and quote == '"':
                esc = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s.rstrip()


def _scalar(tok: str, where: str) -> object:
    tok = tok.strip()
    if tok in ("", "null", "~"):
        return None
    if tok == "true":
        return True
    if tok == "false":
        return False
    if INT_RE.match(tok):
        if len(tok.lstrip("-")) > 1 and tok.lstrip("-").startswith("0"):
            raise GraphError(f"{where}: {tok!r} has a leading zero (YAML 1.1 reads it as octal)")
        return int(tok)
    if tok.startswith('"'):
        try:
            val = json.loads(tok)
        except json.JSONDecodeError as e:
            raise GraphError(f"{where}: bad double-quoted string {tok}: {e}") from None
        if not isinstance(val, str):
            raise GraphError(f"{where}: bad string {tok}")
        return val
    if tok.startswith("'"):
        if len(tok) < 2 or not tok.endswith("'"):
            raise GraphError(f"{where}: unterminated single-quoted string {tok}")
        return tok[1:-1].replace("''", "'")
    if tok[0] in "[]{}*&!|>%@`,?:-#" or ": " in tok or " #" in tok:
        raise GraphError(f"{where}: {tok!r} must be quoted")
    return tok


def _split_flow(body: str, where: str) -> list[str]:
    items, cur, quote, esc = [], [], None, False
    for ch in body:
        if quote:
            cur.append(ch)
            if esc:
                esc = False
            elif ch == "\\" and quote == '"':
                esc = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == ",":
            items.append("".join(cur))
            cur = []
        elif ch in "[]{}":
            raise GraphError(f"{where}: nested collections are not supported")
        else:
            cur.append(ch)
    if quote:
        raise GraphError(f"{where}: unterminated quote in list")
    items.append("".join(cur))
    if items and not items[-1].strip():  # trailing comma, or []
        items.pop()
    if any(not t.strip() for t in items):
        raise GraphError(f"{where}: empty item in list")
    return items


def parse_value(raw: str, where: str = "value") -> object:
    raw = raw.strip()
    if raw.startswith("["):
        if not raw.endswith("]"):
            raise GraphError(f"{where}: a flow list must end with ']' on the same line")
        vals = [_scalar(t, where) for t in _split_flow(raw[1:-1], where)]
        if any(isinstance(v, list) for v in vals):
            raise GraphError(f"{where}: nested lists are not supported")
        return vals
    return _scalar(raw, where)


def format_value(v: object) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(format_value(x) for x in v) + "]"
    s = str(v)
    if PLAIN_RE.match(s) and s not in ("null", "true", "false", "~") and not INT_RE.match(s):
        return s
    return json.dumps(s, ensure_ascii=False)


def parse(text: str, name: str = "graph.yaml") -> tuple[list[dict], list[tuple[int, int]]]:
    """Nodes, and each node's (first, last) 0-based line span (for in-place edits)."""
    nodes: list[dict] = []
    spans: list[tuple[int, int]] = []
    cur: dict | None = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        where = f"{name}:{i + 1}"
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise GraphError(f"{where}: tabs in indentation")
        body = _strip_comment(line)
        if not body.strip():
            continue
        if body.startswith("- "):
            cur = {}
            nodes.append(cur)
            spans.append((i, i))
            kv = body[2:]
        elif body.startswith("  ") and not body.startswith("   ") and cur is not None:
            kv = body[2:]
        else:
            raise GraphError(f"{where}: expected '- key: value' or '  key: value', got {line!r}")
        m = KEY_RE.match(kv)
        if not m:
            raise GraphError(f"{where}: expected 'key: value', got {kv!r}")
        key = m.group(1)
        if key in cur:
            raise GraphError(f"{where}: duplicate key {key!r}")
        cur[key] = parse_value(m.group(2) or "", where)
        spans[-1] = (spans[-1][0], i)
    return nodes, spans


# ---------------------------------------------------------------- globs


def _seg_overlap(a: str, b: str) -> bool:
    """Could one path segment match both patterns? Conservative: unsure means yes."""
    wild = set("*?[")
    wa, wb = bool(wild & set(a)), bool(wild & set(b))
    if not wa and not wb:
        return a == b
    if not wa:
        return fnmatchcase(a, b)
    if not wb:
        return fnmatchcase(b, a)

    def fixed_prefix(p: str) -> str:
        return re.split(r"[*?\[]", p, maxsplit=1)[0]

    def fixed_suffix(p: str) -> str:
        return re.split(r"[*?\]]", p[::-1], maxsplit=1)[0][::-1]

    pa, pb = fixed_prefix(a), fixed_prefix(b)
    sa, sb = fixed_suffix(a), fixed_suffix(b)
    return (pa.startswith(pb) or pb.startswith(pa)) and (sa.endswith(sb) or sb.endswith(sa))


@lru_cache(maxsize=4096)
def _overlap(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    if not a and not b:
        return True
    if not a:
        return all(s == "**" for s in b)
    if not b:
        return all(s == "**" for s in a)
    if a[0] == "**":
        return _overlap(a[1:], b) or _overlap(a, b[1:])
    if b[0] == "**":
        return _overlap(a, b[1:]) or _overlap(a[1:], b)
    return _seg_overlap(a[0], b[0]) and _overlap(a[1:], b[1:])


def globs_overlap(a: str, b: str) -> bool:
    """True when some repo path could match both globs (`**` = any number of dirs)."""

    def split(g: str) -> tuple[str, ...]:
        return tuple(s for s in g.strip("/").split("/") if s)

    return _overlap(split(a), split(b))


def touches_overlap(a: list[str], b: list[str]) -> list[tuple[str, str]]:
    return [(x, y) for x in a for y in b if globs_overlap(x, y)]


# ---------------------------------------------------------------- the graph


def check(nodes: list[dict]) -> tuple[list[str], list[str]]:
    """(errors, warnings)."""
    errs: list[str] = []
    warns: list[str] = []
    ids: dict[str, int] = {}
    for n, node in enumerate(nodes):
        label = node.get("id", f"#{n + 1}")
        for key, (types, required) in FIELDS.items():
            if key not in node:
                if required:
                    errs.append(f"{label}: missing {key}")
                continue
            if not isinstance(node[key], types) or (
                isinstance(node[key], bool) and bool not in types
            ):
                errs.append(f"{label}: {key} has the wrong type ({node[key]!r})")
        for key in node:
            if key not in FIELDS:
                errs.append(f"{label}: unknown field {key!r}")
        for key in ("spec", "depends_on", "touches", "agents", "tiebreak_among"):
            if isinstance(node.get(key), list) and not all(isinstance(x, str) for x in node[key]):
                errs.append(f"{label}: {key} must be a list of strings")
        nid = node.get("id")
        if isinstance(nid, str):
            if not ID_RE.match(nid):
                errs.append(f"{nid}: id must be lowercase letters, digits and dashes")
            if nid in ids:
                errs.append(f"{nid}: duplicate id")
            ids[nid] = n
        if node.get("state") not in STATES:
            errs.append(f"{label}: state {node.get('state')!r} is not one of {'|'.join(STATES)}")
        if node.get("gate", "light") not in GATES:
            errs.append(f"{label}: gate must be one of {'|'.join(GATES)}")
    by_id = {n["id"]: n for n in nodes if isinstance(n.get("id"), str)}
    for node in by_id.values():
        for d in node.get("depends_on") or []:
            if d == node["id"]:
                errs.append(f"{node['id']}: depends on itself")
            elif d not in by_id:
                errs.append(f"{node['id']}: depends on unknown id {d!r}")
    cyc = find_cycle(by_id)
    if cyc:
        errs.append("cycle: " + " -> ".join(cyc))
    for node in by_id.values():
        if node.get("state") in DONE | RUNNING:
            for d in node.get("depends_on") or []:
                dep = by_id.get(d)
                if dep and dep.get("state") not in DONE and node.get("state") in DONE:
                    warns.append(f"{node['id']} is {node['state']} but {d} is {dep['state']}")
    running = [n for n in by_id.values() if n.get("state") in RUNNING]
    for i, a in enumerate(running):
        for b in running[i + 1 :]:
            if a.get("branch") and a.get("branch") == b.get("branch"):
                continue  # one branch, one owner
            hits = touches_overlap(a.get("touches") or [], b.get("touches") or [])
            if hits:
                warns.append(
                    f"running nodes {a['id']} and {b['id']} overlap: "
                    + ", ".join(f"{x} ~ {y}" for x, y in hits[:3])
                )
    return errs, warns


def find_cycle(by_id: dict[str, dict]) -> list[str] | None:
    WHITE, GREY, BLACK = 0, 1, 2
    color = dict.fromkeys(by_id, WHITE)
    stack: list[str] = []

    def visit(u: str) -> list[str] | None:
        color[u] = GREY
        stack.append(u)
        for v in by_id[u].get("depends_on") or []:
            if v not in by_id:
                continue
            if color[v] == GREY:
                return [*stack[stack.index(v) :], v]
            if color[v] == WHITE:
                found = visit(v)
                if found:
                    return found
        stack.pop()
        color[u] = BLACK
        return None

    for u in by_id:
        if color[u] == WHITE:
            found = visit(u)
            if found:
                return found
    return None


def rank_key(node: dict) -> tuple:
    ov = node.get("user_override")
    return (
        0 if ov is not None else 1,
        ov if ov is not None else 0,
        0 if node.get("visible") else 1,
        node.get("priority", 0),
        node.get("plan", 0),
    )


def ready(nodes: list[dict], claimed: set[str] | None = None) -> tuple[list[dict], dict[str, str]]:
    """(ready nodes in rank order, {held node id: why})."""
    claimed = claimed or set()
    by_id = {n["id"]: n for n in nodes}
    running = [n for n in nodes if n["state"] in RUNNING or n["id"] in claimed]
    out: list[dict] = []
    held: dict[str, str] = {}
    cands = sorted(
        (n for n in nodes if n["state"] == "todo" and n["id"] not in claimed),
        key=lambda n: (rank_key(n), nodes.index(n)),
    )
    for n in cands:
        if n.get("blocked"):
            held[n["id"]] = f"blocked: {n['blocked']}"
            continue
        waiting = [d for d in n["depends_on"] if by_id[d]["state"] not in DONE]
        if waiting:
            held[n["id"]] = "waits on " + ", ".join(f"{d} ({by_id[d]['state']})" for d in waiting)
            continue
        clash = next((r for r in running if touches_overlap(n["touches"], r["touches"])), None)
        if clash:
            held[n["id"]] = f"touches overlap running {clash['id']}"
            continue
        clash = next((r for r in out if touches_overlap(n["touches"], r["touches"])), None)
        if clash:
            held[n["id"]] = f"touches overlap higher-ranked ready {clash['id']}"
            continue
        out.append(n)
    return out, held


def pick(ready_nodes: list[dict], rng: random.Random | None) -> tuple[dict | None, list[dict]]:
    """(chosen, the tied group it came from). rng=None takes the first of a tie."""
    if not ready_nodes:
        return None, []
    top = rank_key(ready_nodes[0])
    tied = [n for n in ready_nodes if rank_key(n) == top]
    if len(tied) == 1 or rng is None:
        return tied[0], tied
    return rng.choice(tied), tied


# ---------------------------------------------------------------- file I/O


def load(path: Path) -> tuple[list[dict], list[tuple[int, int]], list[str]]:
    text = path.read_text(encoding="utf-8")
    nodes, spans = parse(text, path.name)
    return nodes, spans, text.splitlines(keepends=True)


def load_checked(path: Path) -> list[dict]:
    nodes, _, _ = load(path)
    errs, _ = check(nodes)
    if errs:
        raise GraphError("graph is invalid, run `graph.py check`:\n  " + "\n  ".join(errs))
    return nodes


def edit(path: Path, node_id: str, changes: dict[str, object]) -> None:
    """Set fields on one node by editing its lines in place, then re-check the whole file."""
    nodes, spans, lines = load(path)
    idx = next((i for i, n in enumerate(nodes) if n.get("id") == node_id), None)
    if idx is None:
        raise GraphError(f"unknown id {node_id!r}")
    for key, val in changes.items():
        if key == "id":
            raise GraphError("ids are stable: never rename one")
        if key not in FIELDS:
            raise GraphError(f"unknown field {key!r}")
        if key == "state" and val not in STATES:
            raise GraphError(f"state {val!r} is not one of {'|'.join(STATES)}")
        first, last = spans[idx]
        new = f"  {key}: {format_value(val)}\n"
        for j in range(first, last + 1):
            body = lines[j][2:] if lines[j].startswith(("- ", "  ")) else ""
            if re.match(rf"^{key}:(\s|$)", body):
                lines[j] = (lines[j][:2] if j == first else "  ") + new[2:]
                break
        else:
            eol = lines[last] if lines[last].endswith("\n") else lines[last] + "\n"
            lines[last] = eol
            lines.insert(last + 1, new)
            spans = [(a + (1 if a > last else 0), b + (1 if b > last else 0)) for a, b in spans]
            spans[idx] = (first, last + 1)
    text = "".join(lines)
    new_nodes, _ = parse(text, path.name)
    errs, _ = check(new_nodes)
    if errs:
        raise GraphError("refusing to write an invalid graph:\n  " + "\n  ".join(errs))
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main_checkout() -> Path:
    """The main checkout (the parent of the shared .git), from any worktree."""
    try:
        common = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()  # fmt: skip
        return Path(common).parent
    except (OSError, subprocess.CalledProcessError):
        return REPO


def default_graph() -> Path:
    env = os.environ.get("DMI_LEAD_GRAPH")
    if env:
        return Path(env)
    return main_checkout() / "claude-plans" / "graph.yaml"


def default_state_dir() -> Path:
    env = os.environ.get("DMI_LEAD_STATE")
    if env:
        return Path(env)
    return main_checkout() / ".worktrees" / ".state"


def _git(cwd: Path, *args: str) -> str | None:
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else None


def commit_board(path: Path, subject: str) -> None:
    """Commit the board file, and only it, on the trunk, when this runs from the checkout
    that holds it (the main checkout) and that checkout is on the trunk. Anywhere else the
    file is left written but uncommitted, and we say so: a board change nobody commits is
    one the next lead can lose."""
    path = path.resolve()
    if _git(path.parent, "ls-files", "--error-unmatch", path.name) is None:
        return  # not in git (a test file, a scratch board)
    top = _git(path.parent, "rev-parse", "--show-toplevel")
    here = _git(Path.cwd(), "rev-parse", "--show-toplevel")
    branch = _git(path.parent, "symbolic-ref", "--quiet", "--short", "HEAD")
    trunk = os.environ.get("DMI_TRUNK", "main")
    why = None
    if here is None or top is None or Path(here).resolve() != Path(top).resolve():
        why = f"run from {here or Path.cwd()}, not from the board's checkout {top}"
    elif branch != trunk:
        why = f"{top} is on {branch or 'a detached HEAD'}, not {trunk}"
    if why:
        print(
            f"note: {path} written but not committed ({why}). "
            "The lead commits it from the main checkout.",
            file=sys.stderr,
        )
        return
    msg = f"{subject}\n\n{os.environ.get('DMI_COMMIT_TRAILER', TRAILER)}"
    done = subprocess.run(
        ["git", "-C", str(path.parent), "commit", "--quiet", "-m", msg, "--", path.name],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if done.returncode != 0 and "nothing to commit" not in done.stdout + done.stderr:
        print(f"warning: the board change isn't committed: {done.stderr.strip()}", file=sys.stderr)


def claimed_ids(state_dir: Path) -> set[str]:
    d = state_dir / "claims"
    return {p.name for p in d.iterdir() if p.is_dir()} if d.is_dir() else set()


# ---------------------------------------------------------------- CLI


def _table(rows: list[list[str]], head: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [head, *rows]) for i in range(len(head))]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    out = [fmt.format(*head), fmt.format(*("-" * w for w in widths))]
    out += [fmt.format(*r).rstrip() for r in rows]
    return "\n".join(out)


def _short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def cmd_check(args: argparse.Namespace) -> int:
    nodes, _, _ = load(args.graph)
    errs, warns = check(nodes)
    for w in warns:
        print(f"warning: {w}")
    for e in errs:
        print(f"error: {e}")
    print(f"graph: {len(nodes)} nodes, {len(errs)} error(s), {len(warns)} warning(s)")
    return 1 if errs else 0


def cmd_ready(args: argparse.Namespace) -> int:
    nodes = load_checked(args.graph)
    claimed = claimed_ids(args.state_dir)
    out, held = ready(nodes, claimed)
    rows = []
    for i, n in enumerate(out, 1):
        ov = n["user_override"]
        vis = "yes" if n["visible"] else ""
        ovr = "" if ov is None else str(ov)
        rows.append(
            [
                str(i),
                n["id"],
                vis,
                str(n["priority"]),
                ovr,
                f"{n['plan']:02d}",
                _short(n["title"], 60),
            ]
        )
    if rows:
        print(_table(rows, ["#", "id", "visible", "prio", "override", "plan", "title"]))
    else:
        print("nothing is ready")
    if held and args.verbose:
        print("\nheld:")
        for k, why in held.items():
            print(f"  {k}: {why}")
    return 0


def cmd_pick(args: argparse.Namespace) -> int:
    nodes = load_checked(args.graph)
    out, _ = ready(nodes, claimed_ids(args.state_dir))
    rng = random.Random(args.seed) if args.random_ties else None
    chosen, tied = pick(out, rng)
    if not chosen:
        print("nothing is ready", file=sys.stderr)
        return 1
    if len(tied) > 1:
        among = [n["id"] for n in tied]
        how = "random" if rng else "first in file order (pass --random-ties)"
        print(f"tie between {', '.join(among)}: picked {chosen['id']} ({how})", file=sys.stderr)
        if rng and not args.no_log:
            edit(args.graph, chosen["id"], {"tiebreak": "random", "tiebreak_among": among})
            if not args.no_commit:
                commit_board(args.graph, f"Graph: {chosen['id']} picked at random among a tie")
            log = args.state_dir / "tiebreaks.log"
            try:
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open("a", encoding="utf-8") as f:
                    # timezone.utc, not datetime.UTC: the system python3 that runs this is 3.10
                    now = dt.datetime.now(dt.timezone.utc)  # noqa: UP017
                    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                    f.write(f"{stamp} picked {chosen['id']} among {','.join(among)}\n")
            except OSError as e:
                print(f"warning: couldn't append to {log}: {e}", file=sys.stderr)
    print(chosen["id"])
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    nodes, _, _ = load(args.graph)
    claimed = claimed_ids(args.state_dir)
    order = {s: i for i, s in enumerate(("review", "ready", "built", "building", "claimed",
                                         "todo", "merged", "dropped"))}  # fmt: skip
    rows = []
    for n in sorted(nodes, key=lambda n: (order.get(n.get("state"), 9), rank_key(n))):
        state = n.get("state", "?") + ("*" if n.get("id") in claimed else "")
        extra = f"blocked: {n['blocked']}" if n.get("blocked") else (n.get("note") or "")
        rows.append([n.get("id", "?"), state, "yes" if n.get("visible") else "",
                     str(n.get("priority", "")), n.get("gate", "light"), f"{n.get('plan', 0):02d}",
                     n.get("branch") or "", ",".join(n.get("depends_on") or []),
                     _short(n.get("title", ""), 48), _short(extra, 40)])  # fmt: skip
    print(_table(rows, ["id", "state", "visible", "prio", "gate", "plan", "branch", "depends_on",
                        "title", "note"]))  # fmt: skip
    if claimed:
        print("\n* = claimed on this Mac (scripts/lead/claim.sh locks)")
    return 0


def cmd_get(args: argparse.Namespace) -> int:
    nodes, _, _ = load(args.graph)
    node = next((n for n in nodes if n.get("id") == args.id), None)
    if node is None:
        print(f"unknown id {args.id!r}", file=sys.stderr)
        return 1
    if args.field is None:
        print(json.dumps(node, indent=2))
        return 0
    val = node.get(args.field)
    if isinstance(val, list):
        print("\n".join(val))
    elif val is None:
        print()
    elif isinstance(val, bool):
        print("true" if val else "false")
    else:
        print(val)
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    changes: dict[str, object] = {}
    for pair in args.pairs:
        key, sep, raw = pair.partition("=")
        if not sep:
            print(f"expected key=value, got {pair!r}", file=sys.stderr)
            return 2
        changes[key.strip()] = parse_value(raw, key)
    edit(args.graph, args.id, changes)
    for k, v in changes.items():
        print(f"{args.id}: {k} = {format_value(v)}")
    if not args.no_commit:
        what = " ".join(f"{k}={format_value(v)}" for k, v in changes.items())
        commit_board(args.graph, f"Graph: {args.id} {_short(what, 60)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="The board (claude-plans/graph.yaml).")
    ap.add_argument("--graph", type=Path, default=None)
    ap.add_argument("--state-dir", type=Path, default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    r = sub.add_parser("ready")
    r.add_argument("-v", "--verbose", action="store_true", help="also list held nodes and why")
    p = sub.add_parser("pick")
    p.add_argument("--random-ties", action="store_true")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--no-log", action="store_true", help="don't record the tie-break")
    p.add_argument("--no-commit", action="store_true", help="don't commit the tie-break")
    sub.add_parser("show")
    g = sub.add_parser("get")
    g.add_argument("id")
    g.add_argument("field", nargs="?")
    s = sub.add_parser("set")
    s.add_argument("id")
    s.add_argument("pairs", nargs="+", metavar="key=value")
    s.add_argument("--no-commit", action="store_true", help="write the file, don't commit it")
    args = ap.parse_args(argv)
    if args.graph is None:
        args.graph = default_graph()
    if args.state_dir is None:
        args.state_dir = default_state_dir()
    if not args.graph.is_file():
        print(
            f"error: no board at {args.graph} (scripts/lead/README.md, 'The board')",
            file=sys.stderr,
        )
        return 1
    cmds = {"check": cmd_check, "ready": cmd_ready, "pick": cmd_pick, "show": cmd_show,
            "get": cmd_get, "set": cmd_set}  # fmt: skip
    try:
        return cmds[args.cmd](args)
    except GraphError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
