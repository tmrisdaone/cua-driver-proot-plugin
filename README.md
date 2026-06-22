# cua-driver-proot (hermes plugin)

Run [cua-driver-rs](https://github.com/trycua/cua) (the cua computer-use agent daemon) inside Termux's `proot-distro` ubuntu rootfs so Hermes can drive a real X11 desktop from a phone.

The daemon is a Rust binary that controls clicks, types, screenshots, and AX-tree walks over the [Model Context Protocol](https://modelcontextprotocol.io/). The official macOS binary is closed; this plugin uses the open-source Rust port which ships prebuilt `linux-arm64` and `linux-x86_64` binaries that run cleanly inside a proot Ubuntu on Termux.

## What you get

Four first-class hermes tools under the `cua_driver` toolset:

| tool | purpose |
|---|---|
| `cua_driver_install`     | apt deps + binary download + Termux-side wrapper. Idempotent — re-running it upgrades. |
| `cua_driver_doctor`      | Health report: binary / X11 / AT-SPI / lib. |
| `cua_driver_upgrade`     | Upgrade to the latest cua-driver-rs release. |
| `cua_driver_atspi_setup` | Start a D-Bus session inside proot so AT-SPI (the AX tree) becomes reachable. |

Plus the bundled `cua-driver-proot` skill — recipe + troubleshooting + the architecture diagram.

## Install

```bash
hermes plugins install tmrisdaone/cua-driver-proot
hermes plugins enable cua-driver-proot
hermes tools                                # confirm cua_driver is listed
hermes tools enable cua_driver              # if not auto-enabled
```

The plugin requires:

- Termux (Android)
- `proot-distro` package (`pkg install proot-distro`)
- a `proot-distro` rootfs named `ubuntu` (`proot-distro install ubuntu`) — or set `PROOT_DISTRO=...` to use a different one
- `termux-x11` running with an X11 desktop (xfce4, mate, etc.) so the daemon has something to control

The plugin itself is ~20 KB; the real install (`cua_driver_install` tool) downloads a 7 MB prebuilt binary and ~30 MB of apt packages on first run.

## Quick start (without the plugin)

If you just want the binary and don't want a hermes plugin:

```bash
curl -fsSL https://raw.githubusercontent.com/tmrisdaone/hermes-skills/main/cua-driver-proot/install.sh | bash
```

Then `cua-driver doctor` from Termux should show:

```
[ok  ] binary: cua-driver 0.6.2 (aarch64-linux)
[ok  ] display server: X11 (DISPLAY=:0)
[ok  ] X11 connection: connected, 4 visible top-level windows
[warn] AT-SPI: accessibility bus not reachable
```

The X11 connection is the win — that's the daemon talking to your termux-x11 desktop. The AT-SPI warning is fixed by `cua_driver_atspi_setup` or by `dbus-run-session`.

## What cua-driver can do (42 tools at v0.6.2)

Without AT-SPI (works immediately after install):

- `list_windows`, `list_apps` — enumerate on-screen windows + installed apps
- `click`, `double_click`, `right_click` — XSendEvent to a specific pid
- `drag`, `mouse_drag`, `parallel_mouse_drag` — pointer gestures (Linux MPX)
- `press_key`, `hotkey` — keyboard input
- `scroll` — wheel events
- `screenshot` — window-scoped JPEG
- `launch_app`, `kill_app` — process control
- `start_recording`, `replay_trajectory` — capture & replay UI sequences
- session / cursor overlay / config tools

With AT-SPI (`cua_driver_atspi_setup` first):

- `get_window_state` — the AX tree walk, the Linux equivalent of macOS AX. Powers element-based clicks.

Full list: `cua-driver list-tools`.

## Architecture

```
┌──────────────┐  spawn  ┌──────────────────┐  exec  ┌─────────────────────┐
│ hermes / any │────────▶│ /usr/bin/cua-    │───────▶│ proot ubuntu:       │
│ Termux tool  │         │ driver (wrapper) │        │ /usr/local/bin/     │
│              │ stdio   │                  │  stdio │ cua-driver mcp      │
└──────────────┘◀────────┴──────────────────┘◀───────┴────────┬────────────┘
                                                             │ X11 + AT-SPI
                                                             ▼
                                                  termux-x11 display server
```

cua-driver-rs is dynamically linked against glibc (`/lib/ld-linux-aarch64.so.1`). Termux uses Android's Bionic libc, so the binary won't run directly in Termux even though the `linux-arm64` asset is the right CPU arch. proot-distro ubuntu is a real arm64 Linux with glibc, so the binary runs cleanly there. The wrapper just `exec`s into proot, forwarding stdin/stdout (the MCP stdio transport) and the X11 socket via `--shared-tmp`.

## Repo layout

```
cua-driver-proot/
├── plugin.yaml
├── __init__.py
├── schemas.py             # JSON schemas for the 4 tools
├── tools.py               # handler implementations
├── install.sh             # one-line installer (apt + binary + wrapper)
├── wrapper/
│   └── cua-driver         # the Termux-side wrapper
└── README.md
```

The companion skill (in the [`hermes-skills`](https://github.com/tmrisdaone/hermes-skills) repo at `cua-driver-proot/`) carries the SKILL.md recipe and the install.sh that this plugin shells out to.

## License

MIT.
