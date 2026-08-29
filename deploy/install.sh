#!/usr/bin/env bash
# Install the knowledge base service on Ubuntu. Idempotent: safe to re-run to upgrade.
#
# Native deployment, no container: the service supervises a child process that keeps a shared
# per-account coordination daemon, and that daemon plus its cache root is far easier to reason
# about when it belongs to one system user on one host.
#
#   sudo ./deploy/install.sh [/srv/knowledge-base]
#
# Leaves behind:
#   /opt/knowledge-base/venv      the Python environment and the `knowledge-base` command
#   /opt/knowledge-base/src       this checkout, which is also where frontend/dist is served from
#   <root>                        the knowledge base itself, owned by the service user

set -euo pipefail

ROOT="${1:-/srv/knowledge-base}"
PREFIX=/opt/knowledge-base
SERVICE_USER=knowledge-base
UNIT=/etc/systemd/system/knowledge-base.service
SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "run me with sudo" >&2
    exit 1
fi

echo "==> System packages"
apt-get update -qq
apt-get install -y -qq git curl

# basic-memory requires Python 3.12, which Ubuntu ships in apt only from 24.04 onwards.
# On 22.04 the interpreter has to come from somewhere else; deadsnakes is the least
# surprising source, and it never replaces the system python.
if ! command -v python3.12 >/dev/null 2>&1; then
    echo "    python3.12 is absent: adding the deadsnakes PPA"
    apt-get install -y -qq software-properties-common
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -qq
fi
apt-get install -y -qq python3.12 python3.12-venv

echo "==> Service user and directories"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home-dir "$ROOT" --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$ROOT" "$PREFIX"
chown -R "$SERVICE_USER:$SERVICE_USER" "$ROOT"

echo "==> Source at $PREFIX/src"
rm -rf "$PREFIX/src"
cp -a "$SOURCE" "$PREFIX/src"

echo "==> Web UI"
if command -v npm >/dev/null 2>&1; then
    (cd "$PREFIX/src/frontend" && npm ci && npm run build)
else
    echo "    npm is absent: skipping the web UI build. The API and the MCP endpoint work"
    echo "    without it; install Node and re-run to get the browser interface."
fi

echo "==> Python environment"
python3.12 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
"$PREFIX/venv/bin/pip" install --quiet "$PREFIX/src"

echo "==> codebase-memory-mcp"
# The code domain's upstream. Absent, the service still runs: documents, search and history
# are unaffected and the code tools report themselves unavailable.
if ! command -v codebase-memory-mcp >/dev/null 2>&1; then
    curl -fsSL https://raw.githubusercontent.com/DeusData/codebase-memory-mcp/main/install.sh | bash
fi
# We decide when a repository is reindexed; its own watcher would do it behind our back.
codebase-memory-mcp config set watcher_enabled false || true
codebase-memory-mcp daemon stop || true

echo "==> Knowledge base root at $ROOT"
sudo -u "$SERVICE_USER" "$PREFIX/venv/bin/knowledge-base" init --root "$ROOT"

echo "==> systemd unit"
sed "s#/srv/knowledge-base#$ROOT#g" "$PREFIX/src/deploy/knowledge-base.service" > "$UNIT"
systemctl daemon-reload
systemctl enable --now knowledge-base
systemctl --no-pager status knowledge-base || true

echo
echo "Done. The service listens on port 8080."
echo "Check it with:  curl -s localhost:8080/api/system/status"
