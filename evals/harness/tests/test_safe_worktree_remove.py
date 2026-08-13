"""Unit tests for the worktree-removal guard (PURE logic; no git, no filesystem).

The incident this guards against: `evals/results/` is gitignored, so a worktree holding a
recorded judged run reports clean under `git status --short`, and `git worktree remove`
deletes it without warning. The classifier is what decides whether that gets caught.
"""
import sys
from pathlib import Path

import importlib.util

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_spec = importlib.util.spec_from_file_location(
    "safe_worktree_remove", PROJECT_ROOT / "scripts" / "safe-worktree-remove.py")
swr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(swr)


def test_parse_ignored_takes_only_ignored_lines():
    porcelain = (
        " M evals/harness/answer_key_score.py\n"
        "?? scratch.txt\n"
        "!! evals/results/\n"
        "!! node_modules/\n"
    )
    assert swr.parse_ignored(porcelain) == ["evals/results/", "node_modules/"]


def test_parse_ignored_unquotes_paths_with_spaces():
    assert swr.parse_ignored('!! "evals/results/run 1/"\n') == ["evals/results/run 1/"]


def test_the_results_directory_itself_is_precious():
    out = swr.classify(["evals/results/"])
    assert out["precious"] == ["evals/results/"] and out["disposable"] == []


def test_a_file_inside_a_results_run_is_precious():
    entry = "evals/results/wordpress-security-critic/critic-pilot-fast-20260811/scorecard.md"
    assert swr.classify([entry])["precious"] == [entry]


def test_an_ancestor_directory_of_the_results_tree_is_precious():
    # If git ever reports the whole `evals/` tree as ignored, removing it still destroys
    # the runs underneath, so the ancestor must be caught too.
    assert swr.classify(["evals/"])["precious"] == ["evals/"]


def test_a_non_directory_ancestor_prefix_is_not_treated_as_an_ancestor():
    # "evals" without a trailing slash is a file, not the tree; it must not match.
    assert swr.classify(["evals"])["disposable"] == ["evals"]


def test_cheap_ignored_paths_stay_disposable():
    entries = ["node_modules/", ".venv/", "__pycache__/", "capability-manifest.json",
               "evals/harness/php-tools/vendor/"]
    out = swr.classify(entries)
    assert out["precious"] == []
    assert out["disposable"] == entries


def test_classify_separates_a_mixed_worktree():
    out = swr.classify(["node_modules/", "evals/results/run-a/", ".pytest_cache/"])
    assert out["precious"] == ["evals/results/run-a/"]
    assert out["disposable"] == ["node_modules/", ".pytest_cache/"]


def test_leading_dot_slash_is_normalized_before_matching():
    assert swr.classify(["./evals/results/run-a/"])["precious"] == ["./evals/results/run-a/"]


def test_precious_prefixes_are_configurable():
    out = swr.classify(["custom/evidence/x.json"], precious_prefixes=("custom/evidence/",))
    assert out["precious"] == ["custom/evidence/x.json"]


def test_refusal_names_the_paths_and_the_ways_out():
    msg = swr.format_refusal("/tmp/wt", ["evals/results/run-a/"])
    assert "REFUSED" in msg and "evals/results/run-a/" in msg
    # the message must be actionable, not just a complaint
    assert "--archive-to" in msg and "--force" in msg and "--check-only" in msg
    # and must explain why the obvious check did not catch it
    assert "git status --short" in msg


def test_refusal_truncates_a_long_list_but_says_how_many_remain():
    msg = swr.format_refusal("/tmp/wt", [f"evals/results/r{i}/" for i in range(25)])
    assert "... and 5 more" in msg
