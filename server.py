"""local-git-mcp: A local MCP server for git operations over HTTP."""

import argparse
import glob
import os
import secrets
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

SENTINEL_FILE = ".git-mcp-allowed"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 44514
DEFAULT_TOKEN_DIR = os.path.expanduser("~/.local/share/local-git-mcp")
DEFAULT_TOKEN_FILE = os.path.join(DEFAULT_TOKEN_DIR, "auth-token")


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------
class BearerTokenMiddleware:
    """ASGI middleware that requires a valid Bearer token on all requests."""

    SKIP_PATHS = {"/health"}

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path not in self.SKIP_PATHS:
                headers = dict(scope.get("headers", []))
                auth = headers.get(b"authorization", b"").decode()
                if auth != f"Bearer {self.token}":
                    response = JSONResponse(
                        {"error": "Unauthorized"}, status_code=401
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------
def load_or_create_token(token_file: str) -> str:
    """Load an existing auth token or generate a new one."""
    path = Path(token_file)
    if path.exists():
        return path.read_text().strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    path.write_text(token + "\n")
    os.chmod(token_file, 0o600)
    return token


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# MCP server and tools
# ---------------------------------------------------------------------------
mcp = FastMCP("local-git-mcp")


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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="local-git-mcp server")
    parser.add_argument(
        "--host",
        default=os.environ.get("LOCAL_GIT_MCP_HOST", DEFAULT_HOST),
        help=f"Bind address (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("LOCAL_GIT_MCP_PORT", DEFAULT_PORT)),
        help=f"Port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--token-file",
        default=os.environ.get("LOCAL_GIT_MCP_TOKEN_FILE", DEFAULT_TOKEN_FILE),
        help=f"Path to auth token file (default: {DEFAULT_TOKEN_FILE})",
    )
    args = parser.parse_args()

    token = load_or_create_token(args.token_file)

    mcp.settings.host = args.host
    mcp.settings.port = args.port

    import anyio
    anyio.run(_run_server, token)


async def _run_server(token: str) -> None:
    import uvicorn
    from starlette.routing import Route

    starlette_app = mcp.streamable_http_app()

    # Add /health route to the existing Starlette app (before auth middleware)
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    starlette_app.routes.insert(0, Route("/health", health))

    # Wrap with auth middleware (skips /health)
    app = BearerTokenMiddleware(starlette_app, token)

    config = uvicorn.Config(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    main()
