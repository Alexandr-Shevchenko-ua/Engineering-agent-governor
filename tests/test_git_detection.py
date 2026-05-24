"""Git worktree detection."""

from pathlib import Path

from governor.gates import is_git_worktree


def test_is_git_worktree_in_governor_repo():
    root = Path(__file__).resolve().parents[1]
    assert is_git_worktree(root) is True


def test_is_git_worktree_false_for_empty_dir(tmp_path):
    assert is_git_worktree(tmp_path) is False
