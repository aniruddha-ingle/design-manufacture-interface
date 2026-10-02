"""Unit tests for scripts/lead/graph.py. Stdlib only:

python3 -m unittest discover -s scripts/lead/tests -p 'test_*.py'
"""

from __future__ import annotations

import contextlib
import io
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import graph  # noqa: E402


def node(nid: str, **kw) -> dict:
    base = {
        "id": nid, "plan": 1, "spec": [], "title": nid, "visible": False, "priority": 10,
        "user_override": None, "depends_on": [], "touches": [], "agents": [],
        "checkpoint": False, "state": "todo", "branch": None,
    }  # fmt: skip
    base.update(kw)
    return base


def to_text(nodes: list[dict]) -> str:
    out = ["# a test graph\n"]
    for n in nodes:
        first = True
        for k, v in n.items():
            out.append(f"{'- ' if first else '  '}{k}: {graph.format_value(v)}\n")
            first = False
        out.append("\n")
    return "".join(out)


class ParseTest(unittest.TestCase):
    def test_round_trip(self):
        nodes = [
            node("a", touches=["src/dmi/render/**", "x.py"], title="A | b: c # d", note=None)
        ]
        parsed, spans = graph.parse(to_text(nodes))
        self.assertEqual(parsed, nodes)
        self.assertEqual(spans, [(1, len(nodes[0]))])

    def test_comments_and_quotes(self):
        text = "- id: a  # trailing\n  title: \"x # not a comment\"\n  spec: ['a,b', c]\n"
        parsed, _ = graph.parse(text)
        self.assertEqual(parsed[0], {"id": "a", "title": "x # not a comment", "spec": ["a,b", "c"]})

    def test_rejects_unquoted_glob_and_leading_zero(self):
        with self.assertRaises(graph.GraphError):
            graph.parse("- id: a\n  touches: [**/x]\n")
        with self.assertRaises(graph.GraphError):
            graph.parse("- id: a\n  plan: 04\n")

    def test_real_graph_is_valid(self):
        board = graph.default_graph()
        if not board.is_file():
            self.skipTest(f"no board at {board}")
        nodes, _, _ = graph.load(board)
        errs, _ = graph.check(nodes)
        self.assertEqual(errs, [])


class CheckTest(unittest.TestCase):
    def test_cycle(self):
        nodes = [node("a", depends_on=["c"]), node("b", depends_on=["a"]),
                 node("c", depends_on=["b"])]  # fmt: skip
        errs, _ = graph.check(nodes)
        cyc = [e for e in errs if e.startswith("cycle:")]
        self.assertEqual(len(cyc), 1, errs)
        for nid in "abc":
            self.assertIn(nid, cyc[0])

    def test_unknown_dep_self_dep_bad_state_unknown_field(self):
        nodes = [node("a", depends_on=["zzz"]), node("b", depends_on=["b"]),
                 node("c", state="wip"), node("d", colour="red")]  # fmt: skip
        errs = "\n".join(graph.check(nodes)[0])
        self.assertIn("unknown id 'zzz'", errs)
        self.assertIn("b: depends on itself", errs)
        self.assertIn("state 'wip'", errs)
        self.assertIn("unknown field 'colour'", errs)

    def test_missing_field_and_duplicate(self):
        n = node("a")
        del n["touches"]
        errs = "\n".join(graph.check([n, node("a")])[0])
        self.assertIn("missing touches", errs)
        self.assertIn("duplicate id", errs)


class OverlapTest(unittest.TestCase):
    def test_globs(self):
        yes = [
            ("web/app/review/**", "web/app/review/queue.ts"),
            ("web/app/**", "web/app/review/**"),
            ("web/e2e/**", "web/e2e/settings-status*"),
            ("**", "anything/at/all"),
            ("api/*.py", "api/x.py"),
            ("api/alembic/versions/0004_*", "api/alembic/versions/**"),
            ("docs/*.md", "docs/a*"),
        ]
        no = [
            ("web/app/review/**", "web/app/settings/**"),
            ("web/app/routes.ts", "web/app/review/**"),
            ("api/alembic/versions/0003_*", "api/alembic/versions/0004_*"),
            ("deploy/**", "api/**"),
            ("api/*.py", "api/x/y.py"),
        ]
        for a, b in yes:
            self.assertTrue(graph.globs_overlap(a, b), (a, b))
            self.assertTrue(graph.globs_overlap(b, a), (b, a))
        for a, b in no:
            self.assertFalse(graph.globs_overlap(a, b), (a, b))
            self.assertFalse(graph.globs_overlap(b, a), (b, a))


class ReadyTest(unittest.TestCase):
    def test_excludes_running_overlap_and_unmerged_deps(self):
        nodes = [
            node("run", state="building", touches=["web/app/review/**"]),
            node("clash", touches=["web/app/review/card.tsx"]),
            node("dep", state="review"),
            node("waits", depends_on=["dep"]),
            node("done", state="merged"),
            node("free", depends_on=["done"], touches=["deploy/**"]),
            node("blocked", blocked="taste"),
        ]
        out, held = graph.ready(nodes)
        self.assertEqual([n["id"] for n in out], ["free"])
        self.assertIn("run", held["clash"])
        self.assertIn("dep (review)", held["waits"])
        self.assertIn("blocked", held["blocked"])

    def test_claims_count_as_running(self):
        nodes = [node("a", touches=["x/**"]), node("b", touches=["x/y"])]
        out, held = graph.ready(nodes, claimed={"a"})
        self.assertEqual(out, [])
        self.assertIn("running a", held["b"])

    def test_never_two_overlapping(self):
        nodes = [node("hi", priority=1, touches=["web/**"]),
                 node("lo", priority=2, touches=["web/app/x.ts"]),
                 node("other", priority=3, touches=["api/**"])]  # fmt: skip
        out, held = graph.ready(nodes)
        self.assertEqual([n["id"] for n in out], ["hi", "other"])
        self.assertIn("higher-ranked ready hi", held["lo"])

    def test_sorting(self):
        nodes = [
            node("plan-late", priority=5, plan=6),
            node("plan-early", priority=5, plan=4),
            node("hidden-first", priority=1),
            node("visible", visible=True, priority=50),
            node("override-2", user_override=2, priority=99),
            node("override-1", user_override=1, priority=99),
        ]
        out, _ = graph.ready(nodes)
        self.assertEqual(
            [n["id"] for n in out],
            ["override-1", "override-2", "visible", "hidden-first", "plan-early", "plan-late"],
        )


class PickTest(unittest.TestCase):
    def tied(self):
        return [node(n, priority=1) for n in ("a", "b", "c", "d")] + [node("e", priority=2)]

    def test_no_tie(self):
        out, _ = graph.ready([node("x", priority=1), node("y", priority=2)])
        chosen, tied = graph.pick(out, random.Random(1))
        self.assertEqual((chosen["id"], len(tied)), ("x", 1))

    def test_seeded_random_tiebreak(self):
        out, _ = graph.ready(self.tied())
        picks = [graph.pick(out, random.Random(seed))[0]["id"] for seed in range(40)]
        self.assertEqual(picks, [graph.pick(out, random.Random(s))[0]["id"] for s in range(40)])
        self.assertEqual(set(picks), {"a", "b", "c", "d"})  # e is ranked lower, never tied
        expect = random.Random(7).choice(out[:4])["id"]
        self.assertEqual(graph.pick(out, random.Random(7))[0]["id"], expect)

    def test_no_rng_takes_first(self):
        out, _ = graph.ready(self.tied())
        chosen, tied = graph.pick(out, None)
        self.assertEqual((chosen["id"], [n["id"] for n in tied]), ("a", ["a", "b", "c", "d"]))

    def test_cli_logs_tiebreak(self):
        with tempfile.TemporaryDirectory() as d:
            g = Path(d) / "graph.yaml"
            g.write_text(to_text(self.tied()), encoding="utf-8")
            state = Path(d) / "state"
            rc = graph.main(["--graph", str(g), "--state-dir", str(state), "pick",
                             "--random-ties", "--seed", "3"])  # fmt: skip
            self.assertEqual(rc, 0)
            want = random.Random(3).choice(["a", "b", "c", "d"])
            nodes, _, _ = graph.load(g)
            chosen = next(n for n in nodes if n["id"] == want)
            self.assertEqual(chosen["tiebreak"], "random")
            self.assertEqual(chosen["tiebreak_among"], ["a", "b", "c", "d"])
            self.assertIn(f"picked {want} among a,b,c,d", (state / "tiebreaks.log").read_text())


class GateTest(unittest.TestCase):
    def test_check_rejects_bad_gate(self):
        errs, _ = graph.check([node("a", gate="medium"), node("b", gate="full")])
        self.assertEqual(len(errs), 1)
        self.assertIn("gate", errs[0])

    def test_check_accepts_built_and_rejects_deployed(self):
        errs, _ = graph.check([node("a", state="built"), node("b", state="deployed")])
        self.assertEqual(len(errs), 1)
        self.assertIn("state 'deployed'", errs[0])


class SetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.g = Path(self.tmp.name) / "graph.yaml"
        self.g.write_text(to_text([node("a"), node("b")]), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_existing_and_new_field_keeps_comments(self):
        graph.edit(self.g, "a", {"state": "building", "branch": "feat/a", "note": "hi: there"})
        text = self.g.read_text()
        self.assertTrue(text.startswith("# a test graph\n"))
        nodes, _, _ = graph.load(self.g)
        self.assertEqual(nodes[0]["state"], "building")
        self.assertEqual(nodes[0]["branch"], "feat/a")
        self.assertEqual(nodes[0]["note"], "hi: there")
        self.assertEqual(nodes[1], node("b"))

    def test_refuses_bad_state_unknown_dep_and_id(self):
        before = self.g.read_text()
        for change in ({"state": "wip"}, {"depends_on": ["nope"]}, {"id": "z"}, {"x": 1}):
            with self.assertRaises(graph.GraphError):
                graph.edit(self.g, "a", change)
        self.assertEqual(self.g.read_text(), before)
        graph.edit(self.g, "a", {"depends_on": ["b"]})
        with self.assertRaisesRegex(graph.GraphError, "cycle"):
            graph.edit(self.g, "b", {"depends_on": ["a"]})
        self.assertEqual(graph.load(self.g)[0][1]["depends_on"], [])

    def test_cli_parses_values(self):
        rc = graph.main(["--graph", str(self.g), "set", "b", "depends_on=[a]", "visible=true",
                         "priority=3"])  # fmt: skip
        self.assertEqual(rc, 0)
        b = graph.load(self.g)[0][1]
        self.assertEqual((b["depends_on"], b["visible"], b["priority"]), (["a"], True, 3))


class CommitTest(unittest.TestCase):
    """The board lives on the trunk: `set` commits it there, and only it, when run from
    the main checkout on the trunk; from anywhere else it writes and says so."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "user.name", "graph test")
        (self.repo / "claude-plans").mkdir()
        self.g = self.repo / "claude-plans" / "graph.yaml"
        self.g.write_text(to_text([node("a"), node("b")]), encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", "a board")
        self.cwd = os.getcwd()
        self.env = os.environ.pop("DMI_TRUNK", None)

    def tearDown(self):
        os.chdir(self.cwd)
        if self.env is not None:
            os.environ["DMI_TRUNK"] = self.env
        self.tmp.cleanup()

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return subprocess.run(
            ["git", "-C", str(cwd or self.repo), *args], capture_output=True, text=True, check=True
        ).stdout.strip()

    def set_(self, *pairs: str, cwd: Path) -> tuple[int, str]:
        os.chdir(cwd)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = graph.main(["--graph", str(self.g), "set", "a", *pairs])
        return rc, err.getvalue()

    def test_from_the_main_checkout_on_main_commits_only_the_board(self):
        (self.repo / "other.txt").write_text("not the board's business\n")
        self.git("add", "other.txt")
        rc, _ = self.set_("state=building", cwd=self.repo / "claude-plans")
        self.assertEqual(rc, 0)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "Graph: a state=building")
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(
            self.git("show", "--name-only", "--format=", "HEAD"), "claude-plans/graph.yaml"
        )
        self.assertIn("Co-Authored-By: Claude Opus 5.5", self.git("log", "-1", "--format=%b"))
        self.assertEqual(self.git("status", "--porcelain"), "A  other.txt")

    def test_from_a_worktree_writes_but_does_not_commit(self):
        wt = Path(self.tmp.name) / "wt"
        self.git("worktree", "add", "--quiet", "-b", "feat", str(wt))
        rc, err = self.set_("state=building", cwd=wt)
        self.assertEqual(rc, 0)
        self.assertIn("not committed", err)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "a board")
        self.assertEqual(self.git("status", "--porcelain"), "M claude-plans/graph.yaml")
        self.assertEqual(self.git("status", "--porcelain", cwd=wt), "")

    def test_main_checkout_off_the_trunk_does_not_commit(self):
        self.git("checkout", "--quiet", "-b", "side")
        rc, err = self.set_("state=building", cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertIn("not main", err)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "a board")

    def test_no_commit_leaves_it_to_the_caller(self):
        rc, err = self.set_("state=building", "--no-commit", cwd=self.repo)
        self.assertEqual(rc, 0)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "a board")
        self.assertEqual(self.git("status", "--porcelain"), "M claude-plans/graph.yaml")


if __name__ == "__main__":
    unittest.main()
