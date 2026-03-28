# local-git-mcp

A lightweight MCP server that handles git operations on behalf of AI coding assistants. Runs locally as a stdio subprocess — no network ports, no external exposure.

## Why?

When AI assistants run inside sandboxed environments with filesystem mounts (e.g. FUSE/bindfs), git lock files (`HEAD.lock`, `index.lock`, etc.) created during commits cannot be cleaned up by the sandbox process due to permission restrictions. This blocks subsequent git operations.

Running git operations through a local MCP server — which executes with full host OS permissions — eliminates this problem entirely.

## Tools

| Tool | Description |
|------|-------------|
| `git_status` | Get `git status` output |
| `git_commit` | Stage and commit changes (with automatic lock file cleanup) |
| `git_log` | View recent commit history |
| `git_diff` | View working tree or staged diffs |
| `git_add` | Stage specific files |
| `git_push` | Push to a remote |
| `git_pull` | Pull from a remote |
| `git_create_branch` | Create (and optionally check out) a new branch |
| `git_checkout` | Check out an existing branch |
| `git_current_branch` | Get the current branch name |

## Installation

### Quick install (recommended)

The install script clones the repo, creates an isolated virtual environment, and registers a system service by default:

```bash
curl -fsSL https://raw.githubusercontent.com/jrokeach/local-git-mcp/main/install.sh | bash
```

To install **without** registering a system service:

```bash
curl -fsSL https://raw.githubusercontent.com/jrokeach/local-git-mcp/main/install.sh | bash -s -- --no-service
```

**What the installer does:**

1. Finds a Python 3.11+ interpreter on your system
2. Clones this repo to `~/.local/share/local-git-mcp` (override with `LOCAL_GIT_MCP_DIR`)
3. Creates a virtual environment and installs the package
4. Unless `--no-service` is passed:
   - **macOS**: Installs a LaunchAgent (`com.local-git-mcp`) that starts at login
   - **Linux**: Installs a systemd user service (`local-git-mcp.service`) that starts at login

The installer prints the full binary path and a ready-to-paste MCP client config snippet when finished.

### Manual install

```bash
git clone https://github.com/jrokeach/local-git-mcp.git
cd local-git-mcp
pip install .        # or: uv pip install .
```

## Uninstallation

```bash
curl -fsSL https://raw.githubusercontent.com/jrokeach/local-git-mcp/main/uninstall.sh | bash
```

This will:
1. Stop and remove the system service (LaunchAgent on macOS, systemd unit on Linux)
2. Delete the installation directory (`~/.local/share/local-git-mcp`)

The uninstaller does **not** remove `.git-mcp-allowed` sentinel files from your repositories or MCP client config entries — those must be cleaned up manually.

If you used a custom install path, set the same environment variable:

```bash
curl -fsSL ... | LOCAL_GIT_MCP_DIR=/your/custom/path bash
```

## Per-Repository Access Control

The server does **not** operate on arbitrary paths. Before executing any git operation, it validates that the target repository has explicitly opted in by checking for a sentinel file.

**To allow the server to operate on a repository**, create a `.git-mcp-allowed` file in the repository root:

```bash
cd /path/to/your/repo
touch .git-mcp-allowed
git add .git-mcp-allowed
git commit -m "Allow local-git-mcp operations"
```

The file may be empty or contain optional freeform notes. If the file is not present, all operations against that repository will be rejected with a clear error message.

**Security rationale:** Without this, any process that can reach the MCP server could request git operations on any directory on the filesystem. The sentinel file ensures that access must be granted intentionally, at the repo level, by someone with write access to that repo.

## MCP Client Configuration

### Claude Code

Add to your MCP settings (e.g. `~/.claude/mcp_settings.json` or project-level `.mcp.json`):

```json
{
  "mcpServers": {
    "local-git-mcp": {
      "command": "local-git-mcp",
      "args": [],
      "type": "stdio"
    }
  }
}
```

If the command isn't on your PATH (e.g. you used the installer), use the full path printed at the end of installation:

```json
{
  "mcpServers": {
    "local-git-mcp": {
      "command": "/path/to/your/.local/share/local-git-mcp/.venv/bin/local-git-mcp",
      "args": [],
      "type": "stdio"
    }
  }
}
```

### Other MCP Clients

Any MCP client that supports stdio transport can use this server. Point it at the `local-git-mcp` command (or the full path to the installed script) with stdio transport.

## Credentials and Authentication

The server **runs as the user who starts it** — whether that's you running it directly, an MCP client spawning it, or a system service started at login. It has no elevated privileges and no credential store of its own.

Every `git` command the server executes inherits that user's environment, which means it uses:

- **SSH keys** from `~/.ssh/` (for `git@` remotes)
- **Git credential helpers** configured in `~/.gitconfig` or `/etc/gitconfig` — e.g. `osxkeychain` on macOS, `libsecret` or `credential-cache` on Linux
- **macOS Keychain** entries (if the user's credential helper is `osxkeychain`)
- **Environment variables** like `GIT_SSH_COMMAND`, `GIT_ASKPASS`, or `SSH_AUTH_SOCK`
- **Git config** from `~/.gitconfig` (user-level) and any repo-level `.git/config`

### On multi-user machines

Each user must install and run their own instance. There is no shared daemon or system-wide service.

- **macOS LaunchAgent** (`~/Library/LaunchAgents/`): A LaunchAgent is a *per-user* service — it runs in your login session with your UID, your home directory, and your keychain. Other users on the same machine cannot see or interact with your agent.
- **Linux systemd user unit** (`~/.config/systemd/user/`): A systemd `--user` service runs in your user session. It has access to your files, your SSH agent socket, and your credential helpers. Other users have their own systemd user instance.

In both cases, the server process can only access repositories that the installing user has filesystem permissions to read/write. Combined with the `.git-mcp-allowed` sentinel requirement, this means:

1. The server only operates on repos the user has filesystem access to
2. Among those, it only operates on repos that have explicitly opted in
3. Git operations authenticate using that user's existing credential setup

**No credentials are stored, managed, or proxied by the server.** If `git push` or `git pull` encounters an authentication error, the error is returned as-is from git. The server sets `GIT_TERMINAL_PROMPT=0` implicitly (via non-interactive subprocess execution), so credential prompts that require a TTY will fail with a clear error rather than hanging.

## Security Model

- **Sentinel file required**: Every repository must contain a `.git-mcp-allowed` file before the server will execute any git commands against it. This is the sole access control mechanism — the server is stateless and config-free.
- **Repository validation**: The server verifies that `repo_path` points to a real git repository (contains a `.git` directory) before executing any command.
- **No network exposure**: stdio transport only — the server is never bound to a port.
- **No hardcoded paths**: All repository paths are passed as parameters at call time.
- **Lock file cleanup**: `git_commit` automatically cleans up stale `.lock` files in `.git/` before and after operations, solving the sandbox permission issue.
- **No credentials stored**: The server delegates all authentication to the host OS's existing git credential configuration.
- **Per-user isolation**: Each user runs their own instance with their own credentials. No shared state between users.

## License

MIT
