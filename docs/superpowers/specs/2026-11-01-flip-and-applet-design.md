# One-click flip: `cosmic-rice flip` and a panel applet

## Why

Changing rice works, but it leaves manual steps: importing the theme, picking a wallpaper, `exec zsh`,
restarting Neovim. The owner wants one click in the COSMIC panel that flips between the two halves of the
current rice and changes everything. Anything that cannot be changed must be shown as an exact step, so
nothing is left to remember.

## Goals

- One click flips dark to light and back, for the current rice's pair.
- The click covers: config files, COSMIC theme, wallpaper, open Neovim, open zsh shells.
- Whatever cannot be done automatically appears once, as a notification with the exact step.
- The same flip works from a terminal or a keyboard shortcut, without the applet.

## Non-goals

- Picking any of the 28 rices from the applet. The owner chose flip only. `cosmic-rice switch` stays the
  way to change rice.
- Removing `switch.sh` or moving the settings block. That is separate work.
- Flatpak or COSMIC Store packaging.

## Anti-goals

- Closing or disturbing open terminals or editors. A half-typed command must survive.
- A wallpaper the owner did not choose replacing one they did, where the rice offers a matching one.
- A flip that leaves the desktop half-changed with no explanation.

## What was tested on 2026-11-01

| Step | Result |
|---|---|
| `cosmic-settings appearance import <file>.ron` | Real desktop: applied the theme and set the mode |
| Editing `source` in `com.system76.CosmicBackground/v1/all` | Real desktop: wallpaper changed; `same-on-all` is true |
| Reload in zsh on USR1 through a trap | Real interactive zsh in a pty: reloaded, half-typed line survived |
| `nvim --server <addr> --remote-expr "execute('colorscheme x')"` | Two real instances over TCP: colours and `background` changed |
| Finding running Neovims by socket | Not tested: the sandbox blocks Unix sockets |
| Terminal scheme | Not tested: stored as a map in `com.system76.CosmicTerm/v1/color_schemes_<mode>` |

## Stage 1: `cosmic-rice flip`

Stays in `cosmic_rice.py`, Python standard library only. Target is the active rice's pair. Errors clearly
if there is no active rice or no pair. Accepts `--keep-icons`.

Steps, in order:

1. **Config:** the existing `switch()` with `steps=False`. It runs first so `~/update_system.sh` and
   `is_dark` already name the new half, and a running `pair --watch` sees nothing to do.
2. **Theme:** `cosmic-settings appearance import <repo>/cosmic/<RON>`.
3. **Wallpaper:** rewrite only the `source: Path("...")` value in the `all` entry, keeping the other fields
   and a `.bak`. Only when `same-on-all` is true; otherwise add a manual step, because per-monitor entries
   are out of scope.
4. **Neovim:** for each socket under the runtime dir (`$XDG_RUNTIME_DIR/**/nvim.*`), run
   `colorscheme <slug>` remotely, where the name comes from the rice's `nvim/colors/*.lua`. A dead socket
   is skipped. A running Neovim is never closed.
5. **zsh:** signal registered shells only (see below).
6. **Report:** `notify-send` with what is left, also printed to stdout.

A failed step does not stop later ones. Failures are added to the report and the exit code is 1.

### Wallpaper choice

Files are named `<slug>-<subject>.png`, and halves share most subjects (Noir and Dossier share 8, Sumi and
SumiDay all 6). Read the current wallpaper. If it belongs to the active rice, use the same subject on the
other half. Otherwise, or if that subject does not exist, use `<slug>-anime.png`, or else the first file
in sorted order. A rice with no `backgrounds/` leaves the wallpaper alone.

### zsh reload

USR1 with no trap kills a zsh, so `pkill -USR1 zsh` would close terminals that started before this
feature. Shells must opt in instead.

- `zsh/reload.zsh` lives in this repo. It defines `TRAPUSR1`, which re-sources the active rice's zsh file,
  found through `~/update_system.sh`, then redraws the prompt if the line editor is active. It records
  `$$` in a file under `$XDG_RUNTIME_DIR/cosmic-rice/zsh/`, removed on exit.
- `flip` signals only the PIDs recorded there, after checking each is still a zsh. Stale files are removed.
- `cosmic-rice install-shell` adds one `source` line to `~/.zshrc`, once, with a `.bak`. `flip` never edits
  `~/.zshrc` for this itself. If the line is missing, the report says to run it.
- Terminals opened before that line was added are not reloaded, and the report cannot see them. This is
  stated in the README.

### Steps left in the report

- **Firefox:** enable this rice's add-on. An add-on cannot be enabled from outside Firefox.
- **Claude Desktop:** pick the theme. `install.sh` only installs the file.
- **COSMIC Terminal:** only if the rice's scheme name is not in `color_schemes_<mode>`, with the import step.

## Stage 2: the applet

- Rust with libcosmic, in `applet/` in this repo, starting from `libcosmic/examples/applet` in
  `cosmic-workbench/upstream`.
- A single panel button. The icon shows the current mode, sun or moon, and follows `is_dark` through
  cosmic-config, so it stays right if the mode changes elsewhere.
- A click runs `cosmic-rice flip` as a subprocess, resolved from `~/.local/bin` then PATH. The button
  ignores clicks and shows a busy state until it exits. A non-zero exit shows a notification; `flip` has
  already reported the details.
- No logic beyond that: everything lives in the CLI.
- Installed for the current user: the binary in `~/.local/bin`, a `.desktop` entry with
  `X-CosmicApplet=true` in `~/.local/share/applications`, then added once in Settings → Panel.

## Testing

- `flip` tests use the fake repos in `tests/test_cli.py`, with stub `cosmic-settings`, `notify-send` and
  `nvim` first on PATH, so no test can touch the live session. Real commands must never run under test.
- `switch` does not gain these live steps, so `tests/test_parity.py` stays valid and stays hermetic.
- zsh reload is tested with a real zsh in a pty, including that an unregistered shell receives no signal.
- The wallpaper rewrite is tested against the real `all` format from the workbench config backup.
- Run the applet against the real panel by hand, because the sandbox cannot.

## Order of work

1. `flip` with theme, wallpaper and report.
2. Neovim, confirming socket discovery on the real desktop.
3. zsh snippet and `install-shell`.
4. Applet.

Stage 1 is useful alone, from a keyboard shortcut. The applet starts only after `flip` works on the real
desktop.

## Calls made by the builder, not the owner

- Wallpaper rule above. The owner did not choose one.
- `flip` is a new command. `switch` and `pair` keep today's behaviour.
- The snippet lives in this repo, with no change to the 28 rice repos.
- The applet lives in this repo rather than its own.
- One notification per flip, with no setting to silence it. Firefox and Claude Desktop will appear every
  time until they can be automated.
- A flip does not take a new backup of `~/.config/cosmic`. It relies on `.bak` files, and the theme import
  has none: COSMIC's own stored theme for that mode is overwritten by the rice's file.
