#!/usr/bin/env bash
# prerequisites.sh — install git, Node.js LTS, and the Claude Code CLI
# on Linux / macOS. Idempotent: skips anything already on PATH.
#
# Detects the package manager (apt, dnf, pacman, zypper, brew) and uses
# whichever is available. Prints a clear error if none is.
#
# Flags:
#   --skip-git     don't try to install git
#   --skip-node    don't try to install node/npm
#   --skip-claude  don't try to install the claude CLI

set -euo pipefail

SKIP_GIT=0
SKIP_NODE=0
SKIP_CLAUDE=0
for arg in "$@"; do
    case "$arg" in
        --skip-git)    SKIP_GIT=1 ;;
        --skip-node)   SKIP_NODE=1 ;;
        --skip-claude) SKIP_CLAUDE=1 ;;
        -h|--help)
            sed -n '2,15p' "$0"; exit 0 ;;
    esac
done

step() { printf '\n==> %s\n'  "$*"; }
ok()   { printf '    OK  %s\n' "$*"; }
warn() { printf '    !!  %s\n' "$*" >&2; }
has()  { command -v "$1" >/dev/null 2>&1; }

# ── Package-manager detection ────────────────────────────────────────────
PM=""
SUDO=""
[ "$EUID" -ne 0 ] && SUDO="sudo"

if   has apt-get;  then PM="apt"
elif has dnf;      then PM="dnf"
elif has pacman;   then PM="pacman"
elif has zypper;   then PM="zypper"
elif has brew;     then PM="brew"; SUDO=""
else
    echo "No supported package manager found (apt/dnf/pacman/zypper/brew)." >&2
    echo "Install git, Node.js LTS, and the Claude Code CLI manually, then re-run." >&2
    exit 1
fi

step "Package manager: $PM"

pm_install() {
    # pm_install <apt-name> [<dnf-name> <pacman-name> <zypper-name> <brew-name>]
    # Falls back to $1 for managers without a specific name.
    local apt_name="$1" dnf_name="${2:-$1}" pacman_name="${3:-$1}" zypper_name="${4:-$1}" brew_name="${5:-$1}"
    case "$PM" in
        apt)     $SUDO apt-get update -qq && $SUDO apt-get install -y "$apt_name" ;;
        dnf)     $SUDO dnf install -y "$dnf_name" ;;
        pacman)  $SUDO pacman -Sy --noconfirm "$pacman_name" ;;
        zypper)  $SUDO zypper --non-interactive install "$zypper_name" ;;
        brew)    brew install "$brew_name" ;;
    esac
}

# ── 1. Git ───────────────────────────────────────────────────────────────
if [ "$SKIP_GIT" -eq 0 ]; then
    if has git; then
        ok "git $(git --version | awk '{print $3}')"
    else
        step "Installing git"
        pm_install git
        ok "git installed"
    fi
fi

# ── 2. Node.js LTS ───────────────────────────────────────────────────────
if [ "$SKIP_NODE" -eq 0 ]; then
    if has node; then
        ok "node $(node --version)"
    else
        step "Installing Node.js LTS"
        case "$PM" in
            apt)
                # NodeSource for Debian/Ubuntu — ships actual LTS, not stale repo version
                curl -fsSL https://deb.nodesource.com/setup_lts.x | $SUDO -E bash - >/dev/null
                $SUDO apt-get install -y nodejs
                ;;
            dnf)
                $SUDO dnf install -y nodejs npm
                ;;
            pacman)
                $SUDO pacman -Sy --noconfirm nodejs npm
                ;;
            zypper)
                $SUDO zypper --non-interactive install nodejs npm
                ;;
            brew)
                brew install node
                ;;
        esac
        ok "node installed ($(node --version 2>/dev/null || echo '?'))"
    fi
fi

# ── 3. Claude Code CLI ───────────────────────────────────────────────────
if [ "$SKIP_CLAUDE" -eq 0 ]; then
    if has claude; then
        ok "claude CLI present ($(claude --version 2>/dev/null | head -1 || echo '?'))"
    else
        step "Installing Claude Code CLI"
        # Official installer — handles Linux/macOS, installs to ~/.local/bin
        if curl -fsSL https://claude.ai/install.sh | bash; then
            ok "claude CLI installed"
            if ! has claude; then
                warn "claude installed but not on PATH. Add ~/.local/bin to PATH:"
                warn "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
                warn "  source ~/.bashrc"
            fi
        else
            warn "Official installer failed. Falling back to npm -g"
            if has npm; then
                $SUDO npm install -g @anthropic-ai/claude-code || warn "npm global install failed"
            else
                warn "npm not available; install Node first, then:  npm i -g @anthropic-ai/claude-code"
            fi
        fi
    fi
fi

# ── 4. Docker check (informational only) ─────────────────────────────────
if has docker; then
    if docker info >/dev/null 2>&1; then
        ok "docker $(docker --version | awk '{print $3}' | tr -d ,) — daemon running"
    else
        warn "docker binary present but daemon not reachable — start it, or add yourself to the docker group:"
        warn "  sudo systemctl start docker"
        warn "  sudo usermod -aG docker \$USER  &&  newgrp docker"
    fi
else
    warn "docker not installed. Langfuse (install-langfuse.sh) will prompt you to install it."
fi

step "Prerequisites phase complete"
cat <<EOF

Next steps:

  ./install.sh --auto-register   # Python stack + MCP server registration
  ./verify.sh                    # sanity check

If any command above printed a PATH warning, open a NEW shell (or source
your shell RC) before continuing.
EOF
