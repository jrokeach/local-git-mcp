"""local-git-mcp: A local MCP server for git operations."""

import glob
import os
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("local-git-mcp")

SENTINEL_FILE = ".git-mcp-allowed"


def _validate_repo(repo_path: str) -> str | None:
    """Validate that repo_path is a git repo with the sentinel file.

    Returns an error message string if validation fails, or None if valid.
    """
    path = Path(repo_path).resolve()

    if not path.is_dir():
        return f"Error: '{repo_path}' is not a directory."

    if not (path / ".git").is_dir():
        return f"Error: '{repo_path}' is not a git repository (no .git directory found)."

    if not (path / SENTINEL_FILE).exists():
        return (
            f"Access denied: {SENTINEL_FILE} not found in {path}. "
            f"Create this file to permit git-mcp operations in this repository."
        )

    return None


def _run_git(repo_path: str, args: list[str], timeout: int = 30) -> str:
    """Run a git command and return its output or a clean error message."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            return f"Error (exit {result.returncode}): {stderr}" if stderr else f"Error (exit {result.returncode})"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return f"Error: git command timed out after {timeout}s."
    except FileNotFoundError:
        return "Error: git is not installed or not in PATH."


def _clean_lock_files(repo_path: str) -> list[str]:
    """Remove stale .lock files from the .git directory. Returns list of removed files."""
    git_dir = os.path.join(repo_path, ".git")
    removed = []
    for lock_file in glob.glob(os.path.join(git_dir, "*.lock")):
        try:
            os.remove(lock_file)
            removed.append(lock_file)
        except OSError:
            pass
    return removed


@mcp.tool()
def git_status(repo_path: str) -> str:
    """Returns the output of `git status` for the given repository path."""
    if err := _validate_repo(repo_path):
        return err
    return _run_git(repo_path, ["status"])


@mcp.tool()
def git_commit(repo_path: str, message: str, stage_all: bool = True) -> str:
    """Commit changes in the repository.

    Cleans up stale .lock files before and after the operation.
    If stage_all is true, runs `git add -A` first.
    """
    if err := _validate_repo(repo_path):
        return err

    _clean_lock_files(repo_path)

    if stage_all:
        add_result = _run_git(repo_path, ["add", "-A"])
        if add_result.startswith("Error"):
            _clean_lock_files(repo_path)
            return f"Failed to stage files: {add_result}"

    result = _run_git(repo_path, ["commit", "-m", message])
    _clean_lock_files(repo_path)
    return result


@mcp.tool()
def git_log(repo_path: str, n: int = 5) -> str:
    """Returns the last n commits as oneline log."""
    if err := _validate_repo(repo_path):
        return err
    return _run_git(repo_path, ["log", "--oneline", f"-{n}"])


@mcp.tool()
def git_diff(repo_path: str, staged: bool = False) -> str:
    """Returns `git diff` or `git diff --staged`."""
    if err := _validate_repo(repo_path):
        return err
    args = ["diff", "--staged"] if staged else ["diff"]
    return _run_git(repo_path, args)


@mcp.tool()
def git_add(repo_path: str, paths: list[str]) -> str:
    """Stages specific files rather than all changes."""
    if err := _validate_repo(repo_path):
        return err
    if not paths:
        return "Error: no paths provided to stage."
    return _run_git(repo_path, ["add", "--"] + paths)


@mcp.tool()
def git_push(repo_path: str, remote: str = "origin", branch: str | None = None) -> str:
    """Pushes to the specified remote and branch.

    If branch is omitted, pushes the current branch.
    Note: may trigger credential prompts depending on host auth setup.
    """
    if err := _validate_repo(repo_path):
        return err
    args = ["push", remote]
    if branch:
        args.append(branch)
    return _run_git(repo_path, args, timeout=60)


@mcp.tool()
def git_pull(repo_path: str, remote: str = "origin", branch: str | None = None) -> str:
    """Pulls from the specified remote and branch.

    If branch is omitted, pulls the current branch.
    """
    if err := _validate_repo(repo_path):
        return err
    args = ["pull", remote]
    if branch:
        args.append(branch)
    return _run_git(repo_path, args, timeout=60)


@mcp.tool()
def git_create_branch(repo_path: str, branch_name: str, checkout: bool = True) -> str:
    """Creates a new branch, optionally checking it out immediately."""
    if err := _validate_repo(repo_path):
        return err
    if checkout:
        return _run_git(repo_path, ["checkout", "-b", branch_name])
    return _run_git(repo_path, ["branch", branch_name])


@mcp.tool()
def git_checkout(repo_path: str, branch_name: str) -> str:
    """Checks out an existing branch."""
    if err := _validate_repo(repo_path):
        return err
    return _run_git(repo_path, ["checkout", branch_name])


@mcp.tool()
def git_current_branch(repo_path: str) -> str:
    """Returns the name of the current branch."""
    if err := _validate_repo(repo_path):
        return err
    return _run_git(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
