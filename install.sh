#!/usr/bin/env bash
# cua-driver-proot installer — installs cua-driver-rs inside proot-distro
# ubuntu and wires up the Termux-side wrapper.
#
# Idempotent: re-running upgrades cua-driver to the latest release.
#
# Usage:  curl -fsSL https://raw.githubusercontent.com/tmrisdaone/hermes-skills/main/cua-driver-proot/install.sh | bash
# Flags:  CUA_DRIVER_RS_VERSION=0.6.0 bash install.sh   # pin a specific version
#         PROOT_DISTRO=debian  bash install.sh          # use debian instead of ubuntu
#         SKIP_APT=1  bash install.sh                    # skip apt (already installed)

set -euo pipefail

# -- config ------------------------------------------------------------------
PROOT_DISTRO="${PROOT_DISTRO:-ubuntu}"
WRAPPER_PATH="${WRAPPER_PATH:-/data/data/com.termux/files/usr/bin/cua-driver}"
SKIP_APT="${SKIP_APT:-0}"
PINNED_VERSION="${CUA_DRIVER_RS_VERSION:-}"

# -- pretty printing ---------------------------------------------------------
RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YLW=$'\033[0;33m'; CYN=$'\033[0;36m'; RST=$'\033[0m'
log()  { printf '%s[cua]%s %s\n' "$CYN" "$RST" "$*"; }
ok()   { printf '%s[cua] ✓%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '%s[cua] !%s %s\n' "$YLW" "$RST" "$*" >&2; }
die()  { printf '%s[cua] ✗%s %s\n' "$RED" "$RST" "$*" >&2; exit 1; }

# -- preflight ---------------------------------------------------------------
command -v proot-distro >/dev/null 2>&1 \
    || die "proot-distro not installed. Run: pkg install proot-distro"

command -v curl >/dev/null 2>&1 \
    || die "curl not installed. Run: pkg install curl"

# proot-distro's `list` output has CR + ANSI clear-to-EOL at the start of
# every line, which makes any regex-based check fragile. Test the rootfs
# directly by logging in — this also catches half-installed/corrupt rootfs.
proot-distro login "$PROOT_DISTRO" -- true >/dev/null 2>&1 \
    || die "${PROOT_DISTRO} rootfs not installed. Run: proot-distro install ${PROOT_DISTRO}"

UNAME_M=$(uname -m)
case "$UNAME_M" in
    aarch64|arm64) ARCH=arm64 ;;
    x86_64|amd64)  ARCH=x86_64 ;;
    *)             die "unsupported arch: $UNAME_M (need aarch64 or x86_64)" ;;
esac

# -- 1. apt deps inside proot ------------------------------------------------
if [ "$SKIP_APT" = "1" ]; then
    log "SKIP_APT=1, skipping apt deps"
else
    log "installing X11 + AT-SPI + D-Bus into ${PROOT_DISTRO} (sudo-free, ~30s)"
    proot-distro login "$PROOT_DISTRO" --shared-tmp -- /bin/bash -c '
        set -e
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y --no-install-recommends \
            libx11-xcb1 libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 \
            libxcb1 libxcb-render0 libxcb-shape0 libxcb-shm0 \
            libxtst6 libxkbcommon0 libxkbfile1 \
            libdbus-1-3 libglib2.0-0 \
            at-spi2-core dbus \
            curl xz-utils ca-certificates >/dev/null
    '
    ok "apt deps installed"
fi

# -- 2. resolve latest version ------------------------------------------------
if [ -z "$PINNED_VERSION" ]; then
    log "resolving latest cua-driver-rs release via GitHub API"
    PINNED_VERSION=$(curl -fsSL "https://api.github.com/repos/trycua/cua/releases?per_page=40" \
        | grep -Eo '"tag_name":[[:space:]]*"cua-driver-rs-v[0-9]+\.[0-9]+\.[0-9]+"' \
        | head -1 \
        | sed -E 's/.*"cua-driver-rs-v([0-9.]+)".*/\1/') \
        || die "could not resolve latest version. Set CUA_DRIVER_RS_VERSION=0.6.2 (or another) and retry."
fi
TAG="cua-driver-rs-v${PINNED_VERSION}"
TARBALL="cua-driver-rs-${PINNED_VERSION}-linux-${ARCH}.tar.gz"
URL="https://github.com/trycua/cua/releases/download/${TAG}/${TARBALL}"
log "installing ${TARBALL}"

# -- 3. download + install into proot ----------------------------------------
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
curl -fsSL --fail -o "$TMPDIR/cua.tgz" "$URL" \
    || die "download failed: $URL"

# tarball expands to ./cua-driver-rs-VERSION-linux-ARCH/cua-driver
proot-distro login "$PROOT_DISTRO" --shared-tmp -- /bin/bash -c "
    set -e
    cd '$TMPDIR'
    tar -xzf cua.tgz
    BIN=\$(find . -name cua-driver -type f | head -1)
    [ -n \"\$BIN\" ] || { echo 'extract failed'; tar -tzf cua.tgz; exit 1; }
    chmod +x \"\$BIN\"
    mv \"\$BIN\" /usr/local/bin/cua-driver
    echo '---installed---'
    /usr/local/bin/cua-driver --version
"
ok "cua-driver ${PINNED_VERSION} installed at /usr/local/bin/cua-driver (inside ${PROOT_DISTRO})"

# -- 4. write the Termux-side wrapper ----------------------------------------
cat > "$WRAPPER_PATH" <<'WRAPPER'
#!/usr/bin/env bash
# Termux-side wrapper for cua-driver running inside proot-distro.
# Hermes (and any other Termux tool that does shutil.which("cua-driver"))
# finds this on $PATH; the script delegates to the cua-driver-rs binary
# installed at /usr/local/bin/cua-driver inside the proot guest.
#
# --shared-tmp exposes termux-x11's X11 socket at /tmp/.X11-unix/X0
# inside the proot guest. stdin/stdout pass through for the MCP stdio
# transport.

set -e
[ -n "${DISPLAY:-}" ] || export DISPLAY=:0

exec proot-distro login __PROOT_DISTRO__ --shared-tmp -- env \
    DISPLAY="${DISPLAY:-:0}" \
    XDG_RUNTIME_DIR=/tmp \
    HOME=/root \
    TERM="${TERM:-xterm-256color}" \
    LANG="${LANG:-C.UTF-8}" \
    LC_ALL="${LC_ALL:-C.UTF-8}" \
    /usr/local/bin/cua-driver "$@"
WRAPPER
# substitute the actual proot distro name into the wrapper
sed -i "s/__PROOT_DISTRO__/${PROOT_DISTRO}/g" "$WRAPPER_PATH"
chmod +x "$WRAPPER_PATH"
ok "wrapper installed at $WRAPPER_PATH"

# -- 5. verify ---------------------------------------------------------------
log "running cua-driver doctor (verifies X11 + binary + libs)"
echo
cua-driver doctor 2>&1 | sed 's/^/    /'
echo

# -- 6. summary --------------------------------------------------------------
cat <<EOF

${GRN}cua-driver-proot is installed.${RST}

  ${CYN}cua-driver --version${RST}     $(cua-driver --version 2>/dev/null || echo 'see warnings above')
  ${CYN}cua-driver doctor${RST}        health report (X11, AT-SPI, version)
  ${CYN}cua-driver list-tools${RST}    42 tools registered
  ${CYN}cua-driver mcp${RST}           MCP stdio transport (what hermes calls)

  ${YLW}next step for hermes:${RST}
    ${CYN}hermes plugins install tmrisdaone/cua-driver-proot-plugin${RST}
    ${CYN}hermes plugins enable cua-driver-proot${RST}

  ${YLW}next step for AT-SPI (get_window_state):${RST}
    proot-distro login ${PROOT_DISTRO} --shared-tmp -- \\
      env DISPLAY=:0 dbus-run-session -- /usr/local/bin/cua-driver mcp

  ${YLW}to upgrade later:${RST} just re-run this script.

EOF
