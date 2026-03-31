# local-git-mcp

A lightweight MCP server that handles git operations on behalf of AI coding assistants. Runs as a local HTTP service — no external network exposure by default.

## Why?

When AI assistants run inside sandboxed environments with filesystem mounts (e.g. FUSE/bindfs), git lock files (`HEAD.lock`, `index.lock`, etc.) created during commits cannot be cleaned up by the sandbox process due to permission restrictions. This blocks subsequent git operations.

A sandboxed agent can't fix this by spawning a helper process — child processes inherit the sandbox. The solution is a persistent service running **outside** the sandbox that the agent connects to over HTTP.

## How It Works

The server runs as a per-user service (macOS LaunchAgent or Linux systemd user unit) outside any sandbox, with full access to your git credentials and filesystem. Your AI agent connects to it over HTTP on `127.0.0.1`.

```
Sandboxed agent ──HTTP──► local-git-mcp service (runs as your user)
                                  ▼
                                 git (full host permissions)
```

An auth token (stored in a file with mode 0600) ensures only your user account can use the service. See [Security Model](#security-model) for details.

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

```bash
curl -fsSL https://raw.githubusercontent.com/jrokeach/local-git-mcp/main/install.sh | bash
```

**What the installer does:**

1. Finds a Python 3.11+ interpreter on your system
2. Clones this repo to `~/.local/share/local-git-mcp` (override with `LOCAL_GIT_MCP_DIR`)
3. Creates a virtual environment and installs the package
4. Generates an auth token at `~/.local/share/local-git-mcp/auth-token` (mode 0600)
5. Checks for required local tools used by the service, including `lsof` for stale lock detection
6. Registers and starts a per-user service:
   - **macOS**: LaunchAgent (`com.local-git-mcp`)
   - **Linux**: systemd user unit (`local-git-mcp.service`)

The installer prints a ready-to-paste MCP client config snippet (with your auth token) when finished. The printed URL uses the default port `44514`; if you run the service on another port, update the URL accordingly.

To install **without** registering a service (e.g. to run manually):

```bash
curl -fsSL https://raw.githubusercontent.com/jrokeach/local-git-mcp/main/install.sh | bash -s -- --no-service
```

### Manual install

```bash
git clone https://github.com/jrokeach/local-git-mcp.git
cd local-git-mcp
pip install .        # or: uv pip install .
local-git-mcp       # starts on 127.0.0.1:44514
```

## Uninstallation

```bash
curl -fsSL https://raw.githubusercontent.com/jrokeach/local-git-mcp/main/uninstall.sh | bash
```

This will:
1. Stop and remove the system service (LaunchAgent on macOS, systemd unit on Linux)
2. Delete the installation directory including the auth token

The uninstaller does **not** remove `.git-mcp-allowed` sentinel files from your repositories or MCP client config entries — those must be cleaned up manually.

If you used a custom install path, set the same environment variable:

```bash
curl -fsSL ... | LOCAL_GIT_MCP_DIR=/your/custom/path bash
```

## MCP Client Configuration

Add to your MCP settings (e.g. `~/.claude/mcp_settings.json` or project-level `.mcp.json`):

```json
{
  "mcpServers": {
    "local-git-mcp": {
      "type": "http",
      "url": "http://127.0.0.1:44514/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
```

Replace `YOUR_TOKEN_HERE` with the contents of `~/.local/share/local-git-mcp/auth-token`. The install script prints the complete config snippet with your token filled in, using the default port `44514`.

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

**Security rationale:** Without this, any process that can authenticate to the server could request git operations on any directory the user has access to. The sentinel file ensures that access must be granted intentionally, at the repo level, by someone with write access to that repo.

## Credentials and Authentication

### How the service authenticates git operations

The service runs as **your user account** (via LaunchAgent or systemd user unit). It is not a system-wide daemon and does not run as root. Because it runs as you, it inherits your full environment:

- **SSH keys** from `~/.ssh/`
- **Git credential helpers** from `~/.gitconfig` (e.g. `osxkeychain` on macOS, `libsecret` on Linux)
- **macOS Keychain** entries
- **Environment variables** like `SSH_AUTH_SOCK`, `GIT_SSH_COMMAND`, `GIT_ASKPASS`
- **Git config** from `~/.gitconfig` and repo-level `.git/config`

No credentials are stored, managed, or proxied by the server. If `git push` or `git pull` encounters an authentication error, the error is returned as-is from git. Because the server runs non-interactively, credential prompts that require terminal input will fail cleanly rather than hanging.

### How the service authenticates clients (auth token)

Every request to the server must include a Bearer token in the `Authorization` header. The token is a random 64-character hex string stored at `~/.local/share/local-git-mcp/auth-token` with file mode `0600` (owner-read-only).

**Why a token is necessary:** The server listens on a TCP port. TCP ports are not scoped to a user — any process running on the machine can connect to any port on `127.0.0.1`. Without a token, any local user or process could send requests to your service and execute git operations using your credentials. The token ensures that only processes that can read your token file (i.e. processes running as your user or as root) can authenticate.

### On multi-user machines

Each user runs their own service instance. The auth token file (`0600`) ensures that user B cannot authenticate to user A's service, even though TCP port access is not user-scoped. If multiple users install the service, each should use a different port (configure via `--port` or `LOCAL_GIT_MCP_PORT`).

The `/health` endpoint is the only unauthenticated endpoint, intentionally, so monitoring tools can check service liveness without a token.

## Configuration

The server accepts configuration via CLI args or environment variables:

| Setting | CLI arg | Env var | Default |
|---------|---------|---------|---------|
| Bind address | `--host` | `LOCAL_GIT_MCP_HOST` | `127.0.0.1` |
| Port | `--port` | `LOCAL_GIT_MCP_PORT` | `44514` |
| Token file | `--token-file` | `LOCAL_GIT_MCP_TOKEN_FILE` | `~/.local/share/local-git-mcp/auth-token` |

To listen on all interfaces (e.g. for remote access from another machine):

```bash
local-git-mcp --host 0.0.0.0
```

When exposing to other machines, ensure the token is shared securely with authorized clients.

## Security Model

- **Auth token required**: Every request (except `/health`) must include a valid Bearer token. The token file is created with mode `0600`, ensuring only the owning user can read it.
- **Sentinel file required**: Every repository must contain a `.git-mcp-allowed` file before the server will execute any git commands against it.
- **Repository validation**: The server verifies that `repo_path` is the actual root of a real git repository by asking Git for the repository toplevel before executing any command.
- **Localhost by default**: Binds to `127.0.0.1`, not accessible from the network. Configurable for intentional remote access.
- **Per-user isolation**: Each user runs their own service with their own token and credentials. No shared state between users.
- **Lock file cleanup**: `git_commit` only removes known stale lock files after checking that they are old enough and not still in use.
- **No credentials stored**: The server delegates all authentication to the host OS's existing git credential configuration.

## Development

Run the minimal regression tests with Python 3.11+:

```bash
python3.11 -m unittest discover -s tests -p 'test_server.py' -v
```

## License

MIT
