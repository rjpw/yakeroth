"""Git utilities for yakeroth site management."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from git import Repo, GitCommandError


class GitError(Exception):
    """Git operation failed."""
    pass


def get_repo(path: Path) -> Repo:
    """Get or initialize git repo at path."""
    try:
        return Repo(path)
    except Exception as e:
        raise GitError(f"Not a git repository: {path}") from e


def ensure_clean_working_tree(repo: Repo, force: bool = False) -> None:
    """Ensure working tree is clean, or raise if not forced."""
    if repo.is_dirty(untracked_files=True):
        if not force:
            raise GitError(
                f"Working tree not clean in {repo.working_tree_dir}. "
                f"Commit or stash changes first, or use --force."
            )


def stage_all(repo: Repo) -> None:
    """Stage all changes (tracked + untracked)."""
    repo.git.add(A=True)


def commit(repo: Repo, message: str) -> str:
    """Create a commit and return its SHA."""
    if not repo.is_dirty(untracked_files=True):
        return repo.head.commit.hexsha

    stage_all(repo)
    commit_obj = repo.index.commit(message)
    return commit_obj.hexsha


def tag(repo: Repo, tag_name: str, message: str | None = None) -> None:
    """Create an annotated tag."""
    if message is None:
        message = tag_name
    repo.create_tag(tag_name, message=message)


def get_short_sha(repo: Repo, rev: str = "HEAD") -> str:
    """Get short SHA for a revision."""
    return repo.git.rev_parse("--short", rev)


def get_file_sha(repo: Repo, file_path: str, rev: str = "HEAD") -> str:
    """Get blob SHA for a file at a revision."""
    try:
        return repo.git.rev_parse(f"{rev}:{file_path}")
    except GitCommandError:
        return ""


def get_current_branch(repo: Repo) -> str:
    """Get current branch name."""
    try:
        return repo.active_branch.name
    except TypeError:
        # Detached HEAD
        return repo.head.commit.hexsha[:8]


def ls_remote_commit(repo_url: str, ref: str) -> str:
    """Resolve a remote ref to a commit SHA using git ls-remote."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", repo_url, ref],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.strip().split("\n"):
            if line.endswith(f"\t{ref}") or line.endswith(f"\trefs/heads/{ref}") or line.endswith(f"\trefs/tags/{ref}"):
                return line.split("\t")[0]
        # Try just the commit hash if ref looks like one
        if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref.lower()):
            return ref
        raise GitError(f"Could not resolve ref '{ref}' in {repo_url}")
    except subprocess.CalledProcessError as e:
        raise GitError(f"git ls-remote failed: {e.stderr}") from e


def clone_or_update(repo_url: str, dest: Path, commit: str, branch: str = "master") -> None:
    """Clone repo or update existing to specific commit."""
    if dest.exists():
        repo = Repo(dest)
        # Verify remote matches
        origin = repo.remotes.origin
        if origin.url != repo_url:
            raise GitError(f"Existing repo at {dest} has different remote: {origin.url} != {repo_url}")
        origin.fetch()
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        repo = Repo.clone_from(repo_url, dest, branch=branch)

    # Checkout specific commit
    repo.git.checkout(commit)


def reset_hard(repo: Repo, target: str = "HEAD") -> None:
    """Hard reset to target (commit, tag, or HEAD~N)."""
    repo.git.reset("--hard", target)


def clean_untracked(repo: Repo, paths: list[str]) -> None:
    """Remove untracked files/dirs at specific paths (known generated paths only)."""
    for path_str in paths:
        path = Path(repo.working_tree_dir) / path_str
        if path.exists():
            if path.is_dir():
                import shutil
                shutil.rmtree(path)
            else:
                path.unlink()


def get_status(repo: Repo) -> dict:
    """Get git status summary."""
    return {
        "dirty": repo.is_dirty(untracked_files=True),
        "untracked": repo.untracked_files,
        "modified": [item.a_path for item in repo.index.diff(None)],
        "staged": [item.a_path for item in repo.index.diff("HEAD")],
        "branch": get_current_branch(repo),
        "head_sha": repo.head.commit.hexsha[:8],
    }


def log_oneline(repo: Repo, path: str | None = None, max_count: int = 20) -> list[str]:
    """Get git log --oneline for a path."""
    args = ["--oneline", f"-{max_count}"]
    if path:
        args.append("--")
        args.append(path)
    return repo.git.log(*args).strip().split("\n")