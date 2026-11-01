# One-click flip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, solo, with no subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `cosmic-rice flip` changes everything for the other half of the current rice, and a panel applet runs it in one click.

**Architecture:** All logic stays in `cosmic_rice.py`. `flip()` calls the existing `switch()`, then live steps that each return leftover messages and never raise past `flip()`. The applet is a thin libcosmic button around a subprocess.

**Tech Stack:** Python 3.10+ standard library, `unittest`, zsh, Rust with libcosmic.

**Spec:** `docs/superpowers/specs/2026-11-01-flip-and-applet-design.md`

## Global Constraints

- `cosmic_rice.py` uses the Python standard library only.
- Tests must never run the real `cosmic-settings`, `notify-send` or `nvim`: stubs go first on PATH.
- `switch()` and `pair` keep today's behaviour, so `tests/test_parity.py` stays valid.
- Signal only recorded zsh PIDs, never `pkill zsh`. USR1 with no trap kills a shell.
- A running Neovim or terminal is never closed.
- Never use em-dashes or en-dashes. Commits use the repo's noreply identity through environment variables, never git config. In the sandbox: `GIT_CONFIG_GLOBAL=/dev/null`, and cargo through `cosmic-workbench/scratch/cargo-env.sh`.
- The user pushes.

## Review Focus

1. Wallpaper path containing spaces or `#`: the rewrite must keep it intact and keep every other field. Task 1 test.
2. Pressing flip twice quickly, or flip while `pair --watch` runs: must end on one half with no double switch. Task 1 test (link and `is_dark` match before the import); Task 4 ignores clicks while busy.
3. `cosmic-settings` missing or failing: config still flips, the report says the theme failed, exit 1. Task 1 test.
4. A recorded PID reused by a non-zsh process: it gets no signal, and its file is removed. Task 3 test.
5. A dead Neovim socket left behind: skipped with no error or hang, using a timeout of 5 seconds. Task 2 test.

---

### Task 1: `flip` with theme, wallpaper and report

**Files:**
- Modify: `cosmic_rice.py`
- Test: `tests/test_flip.py` (create), reusing `fake_rice` and `Base` from `tests/test_cli.py`

**Interfaces:**
- Consumes: `switch(rice, rices, keep_icons, steps)`, `active(rices)`, `find(rices, slug)`, `backup(path)`, `Error`
- Produces: `flip(rices: list[Rice], keep_icons: bool = False) -> bool`; `apply_theme(rice: Rice) -> list[str]`; `apply_wallpaper(rice: Rice, previous: Rice) -> list[str]`; `pick_wallpaper(rice: Rice, previous: Rice, current: str) -> Path | None`; `leftovers(rice: Rice) -> list[str]`. Each list holds messages for the report. `live` steps return failures through the same list, and `flip` returns False if any step failed.

- [ ] **Step 1: Write failing tests**

Stub directory on PATH with `cosmic-settings` and `notify-send` scripts appending argv to a log. Tests:
- `test_flip_moves_to_the_pair_and_imports_its_theme`: log has `appearance import <dossier>/cosmic/Dossier.ron`.
- `test_link_and_mode_are_set_before_the_import`: the stub records `readlink ~/update_system.sh` and `is_dark` when called; they name the new half.
- `test_failed_import_still_flips_and_returns_false`.
- `test_no_active_rice_and_no_pair_raise_error`.
- `test_same_subject_is_kept`: `current` is `<noir>/backgrounds/noir-city.png`, gives `dossier-city.png`.
- `test_missing_subject_falls_back_to_anime_then_first`.
- `test_foreign_wallpaper_uses_anime`.
- `test_no_backgrounds_leaves_wallpaper_alone`.
- `test_rewrite_keeps_other_fields_and_odd_paths`: an `all` file in the real format with a path holding a space and `#`; only `source` changes and `all.bak` exists.
- `test_separate_monitors_become_a_manual_step`: `same-on-all` false, file unchanged, message returned.
- `test_report_lists_firefox_and_claude_and_goes_to_notify_send`.
- `test_scheme_step_only_when_name_is_missing`: `color_schemes_dark` containing `name: "Noir"` gives no terminal step.
- `test_flip_command_exit_codes` through `main(["flip"])`.

- [ ] **Step 2: Run `python3 -m unittest tests.test_flip`.** Expected: errors, `flip` not defined.

- [ ] **Step 3: Implement the functions above and a `flip` subparser with `--keep-icons`.** Rewrite `source` with `re.sub` on `source: Path\("[^"]*"\)` using a function replacement, so backslashes and `#` in paths are safe. `notify-send` missing is not a failure. Run subprocesses with `timeout=30`, catching `OSError` and `subprocess.SubprocessError`.

- [ ] **Step 4: Run `python3 -m unittest discover -s tests`.** Expected: all pass, parity included.

- [ ] **Step 5: Commit** `Add cosmic-rice flip: theme, wallpaper and report`

### Task 2: Neovim

**Files:** Modify `cosmic_rice.py`; test `tests/test_flip.py`

**Interfaces:**
- Produces: `reload_nvim(rice: Rice) -> list[str]`, called by `flip`; `nvim_sockets() -> list[Path]` globbing `nvim.*` recursively under `XDG_RUNTIME_DIR`.

- [ ] **Step 1: Write failing tests** with a stub `nvim` logging argv: `test_each_socket_gets_the_colorscheme`, where the name is the stem of `nvim/colors/*.lua`; `test_dead_socket_is_skipped` (stub exits 1, no failure reported); `test_no_runtime_dir_or_colors_is_quiet`.
- [ ] **Step 2: Run them.** Expected: FAIL, not defined.
- [ ] **Step 3: Implement** using `--server <sock> --remote-expr "execute('colorscheme <name>')"` with `timeout=5`.
- [ ] **Step 4: Run `python3 -m unittest discover -s tests`.** Expected: all pass.
- [ ] **Step 5: Commit** `flip: recolour running Neovims`

### Task 3: zsh reload

**Files:** Create `zsh/reload.zsh`, `tests/test_zsh.py`; modify `cosmic_rice.py`, `README.md`

**Interfaces:**
- Produces: `reload_zsh() -> list[str]`, called by `flip`; `install_shell() -> bool`, behind `cosmic-rice install-shell`. PID files live in `$XDG_RUNTIME_DIR/cosmic-rice/zsh/<pid>`.

- [ ] **Step 1: Write failing tests:** with a real zsh in a pty (pattern proven on 2026-11-01), `test_registered_shell_reloads_keeping_a_half_typed_line`; `test_unregistered_shell_gets_no_signal_and_lives`; `test_pid_of_a_non_zsh_is_not_signalled_and_is_removed`, checking `/proc/<pid>/comm`; `test_install_shell_adds_one_line_once_with_bak`; `test_report_says_run_install_shell_when_line_is_missing`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** `reload.zsh` runs only in interactive shells. It finds the rice from `~/update_system.sh`, sources `<repo>/zsh/*.zsh`, and calls `zle reset-prompt` only when `zle` is active. A `zshexit` hook removes the PID file.
- [ ] **Step 4: Run `python3 -m unittest discover -s tests`.** Expected: all pass.
- [ ] **Step 5: Document `flip` and `install-shell` in the README, including that terminals opened before the line was added are not reloaded.**
- [ ] **Step 6: Commit** `flip: reload registered zsh shells`
- [ ] **Step 7: Stop for a real-desktop check.** The user runs `cosmic-rice install-shell`, opens a terminal with Neovim, runs `cosmic-rice flip` twice, and reports. This confirms Neovim socket discovery and the terminal scheme. Do not start Task 4 until it works.

### Task 4: Applet

**Files:** Create `applet/Cargo.toml`, `applet/src/main.rs`, `applet/data/cosmic-rice-applet.desktop`, `applet/install.sh`; modify `README.md`, `.gitignore`

**Interfaces:**
- Consumes: `cosmic-rice flip` and its exit code.

- [ ] **Step 1: Copy the shape of `cosmic-workbench/upstream/libcosmic/examples/applet`.** Build a single icon button with a `busy: bool` and an `is_dark: bool` updated through a cosmic-config subscription on `com.system76.CosmicTheme.Mode`.
- [ ] **Step 2: Add a unit test for the pure parts:** `icon_name(is_dark) -> &'static str` and `flip_binary() -> PathBuf`, which prefers `~/.local/bin/cosmic-rice`, then PATH. Run `cargo test`. Expected: FAIL, then write them and PASS.
- [ ] **Step 3: On click,** return early if `busy`; otherwise run the binary in a task and clear `busy` on exit. A non-zero exit sends a notification.
- [ ] **Step 4: Run `cargo build --release` and `cargo clippy`.** Expected: no errors.
- [ ] **Step 5: Add `applet/install.sh`,** which copies the binary to `~/.local/bin` and the `.desktop` entry, with `X-CosmicApplet=true`, to `~/.local/share/applications`. The user runs it.
- [ ] **Step 6: Commit** `Add the panel applet`
- [ ] **Step 7: The user adds it in Settings → Panel, clicks it both ways, and reports.**
