#!/usr/bin/env python3
"""Switch between COSMIC rices: the cosmic-*-theme repos next to this one.

  themebox                      tabs for rice, wallpaper, pair, cursors and icons
  themebox list                 every rice, * marks the active one
  themebox switch <slug>        make a rice active
  themebox wallpaper <slug>     list a rice's wallpapers
  themebox wallpaper <slug> <n> save one as the wallpaper for that rice
  themebox pair                 match the rice to COSMIC's light/dark toggle
  themebox pair --watch         keep matching it
  themebox flip                 move to the other half and change everything live
  themebox choose <a> <b>       flip between these two, one dark and one light
  themebox choose --reset       flip between each rice's own pair again
  themebox get <slug>           download a rice and its other half
  themebox capture <name>       save the current theme and wallpaper as a new rice
  themebox install-shell        let flip reload open zsh shells

The active rice is whichever repo ~/update_system.sh links into. Rices are the
cosmic-<slug>-theme folders with a rice.toml, in THEMEBOX_REPOS or else in the
folder that holds this repo. Older ones keep their settings in scripts/switch.sh.
"""
import argparse
import contextlib
import curses
import io
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

SETTING = re.compile(r'^(NAME|MODE|RON|TERM_RON|BTOP)="([^"]*)"', re.M)
OLD_SETTINGS = {"NAME": "name", "MODE": "mode", "RON": "theme", "TERM_RON": "terminal", "BTOP": "btop"}
REQUIRED = ("name", "mode", "theme")
PAIR = re.compile(r"https://github\.com/[^/\s]+/(cosmic-[a-z0-9]+-theme)")
TOOLS = ("fastfetch", "lsd", "bat", "starship", "kitty", "alacritty", "wezterm", "ghostty",
         "delta", "lazygit", "helix", "gtk", "qt", "discord")
LEGACY_NVIM = ("harbordark",)  # the old hand-installed spec, parked like any other
GALLERY = "https://atraxsrc.github.io/cosmic-rices/"
SOURCE = "https://github.com/atraxsrc"  # where themebox get downloads rices from
FAILED = "failed:"  # marks a report line that makes flip exit 1
WALLPAPER = re.compile(r'source: Path\("((?:[^"\\]|\\.)*)"\)')
# ThemeBuilder fields import cannot do without, and the colours that are None until set
THEME_NEEDED = ("palette", "spacing", "corner_radii", "gaps", "active_hint")
THEME_COLORS = ("neutral_tint", "bg_color", "primary_container_bg", "secondary_container_bg", "text_tint",
                "accent", "success", "warning", "destructive", "window_hint")
TK_LOOK = ("apply_theme_global", "icon_theme", "interface_font", "monospace_font", "show_maximize", "show_minimize")
# the CosmicTk settings COSMIC after 1.11.0 reads from the theme instead, by their theme field
THEME_LOOK = {"icon_theme": "icon_theme", "interface_font": "font", "monospace_font": "mono_font"}
ZSH_SOURCE = r"^\s*#?\s*(?:source|\.)\s.*"
ZSH_ANY = re.compile(ZSH_SOURCE + r"(?:cosmic-[a-z0-9]+-theme/zsh/[a-z0-9]+\.zsh|ricing/zsh/colors\.zsh)")
VARIANT_LIST = re.compile(r"^VARIANTS=\(([^)]*)\)", re.M)
XCURSOR_IMAGE = 0xfffd0002  # the chunk type of one image in a cursor file
COLOUR_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*!\[#([0-9a-fA-F]{6})\]\([^)]*\)\s*([^|]*?)\s*\|", re.M)
PANEL_WIDTH = 34  # the palette beside a list, shown once the terminal has room


class Error(Exception):
    """A problem to show the user without a traceback."""


@dataclass
class Rice:
    repo: Path
    name: str
    slug: str
    mode: str
    ron: str
    term_ron: str
    btop: str
    pair: str | None = None


def readme_pair(repo: Path) -> str | None:
    """The other half's repo name, from the link above the palette in the README."""
    readme = repo / "README.md"
    head = readme.read_text().split("## Palette", 1)[0] if readme.is_file() else ""
    return next((p for p in PAIR.findall(head) if p != repo.name), None)


def settings(repo: Path) -> dict[str, str] | None:
    """A rice's rice.toml, or the block in an older rice's switch.sh. None if it has neither."""
    toml, script = repo / "rice.toml", repo / "scripts/switch.sh"
    if toml.is_file():
        source, required = toml, REQUIRED
        try:
            found = tomllib.loads(toml.read_text())
        except tomllib.TOMLDecodeError as err:
            raise Error(f"{toml}: {err}") from None
    elif script.is_file():
        source, required = script, tuple(OLD_SETTINGS)
        found = dict(SETTING.findall(script.read_text()))
    else:
        return None
    missing = [key for key in required if key not in found]
    if missing:
        raise Error(f"{source} needs {', '.join(missing)}")
    if source is script:
        found = {OLD_SETTINGS[key]: text for key, text in found.items()}
    if not all(isinstance(text, str) for text in found.values()):
        raise Error(f"{source}: every setting must be a quoted string")
    if found["mode"] not in ("dark", "light"):
        raise Error(f"{source}: mode must be dark or light, not {found['mode']}")
    return found


def pair_repo(repo: Path) -> str | None:
    """The other half's repo name: rice.toml's pair, else the link in the README."""
    pair = (settings(repo) or {}).get("pair")
    if pair is None:
        return readme_pair(repo)
    if not re.fullmatch(r"[a-z0-9]+", pair):
        raise Error(f"{repo / 'rice.toml'}: {pair} is not a rice name")
    return f"cosmic-{pair}-theme"


def discover(repos: Path) -> list[Rice]:
    rices, pairs = [], {}
    for repo in sorted(Path(repos).glob("cosmic-*-theme")):
        s = settings(repo)
        if s is None:
            continue
        slug = repo.name.removeprefix("cosmic-").removesuffix("-theme")
        rices.append(Rice(repo, s["name"], slug, s["mode"], s["theme"], s.get("terminal", ""), s.get("btop", "")))
        pairs[repo.name] = pair_repo(repo)
    slugs = {r.repo.name: r.slug for r in rices}
    for r in rices:
        r.pair = slugs.get(pairs[r.repo.name])
    for r in rices:  # a pair link in one README is enough
        r.pair = r.pair or next((o.slug for o in rices if o.pair == r.slug), None)
    return rices


def find(rices: list[Rice], wanted: str) -> Rice:
    key = wanted.lower().replace(" ", "")
    for r in rices:
        if key in (r.slug, r.name.lower().replace(" ", "")):
            return r
    raise Error(f"no rice called {wanted!r}, see: themebox list")


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def mode_file() -> Path:
    return config_dir() / "cosmic/com.system76.CosmicTheme.Mode/v1/is_dark"


def current_mode() -> str:
    return "light" if value(mode_file()) == "false" else "dark"


def theme_folder(mode: str, builder: bool = False) -> Path | None:
    """COSMIC's newest stored theme (or theme builder) folder for a mode, None if it has none."""
    root = config_dir() / f"cosmic/com.system76.CosmicTheme.{mode.capitalize()}{'.Builder' if builder else ''}"
    folders = [p for p in root.glob("v*") if p.is_dir() and p.name[1:].isdigit()]
    return max(folders, key=lambda p: int(p.name[1:]), default=None)


def theme_icons(mode: str) -> Path | None:
    """The icon theme setting inside COSMIC's theme. COSMIC after 1.11.0 reads it there
    instead of CosmicTk; None on an older COSMIC, whose theme has no such field."""
    folder = theme_folder(mode)
    return folder / "icon_theme" if folder and (folder / "icon_theme").is_file() else None


def set_theme_icons(mode: str, name: str) -> None:
    """Put an icon theme into COSMIC's theme and theme builder for one mode, if they hold one."""
    if not name or theme_icons(mode) is None:
        return
    for builder in (False, True):
        folder = theme_folder(mode, builder)
        if folder and value(folder / "icon_theme") != name:
            (folder / "icon_theme").write_text(f'"{name}"')


def wallpaper_folder(mode: str) -> Path:
    """cosmic-bg's settings for one mode. cosmic-bg after 1.11.0 keeps one folder per mode and
    copies the shared one in only when it starts, so the shared one is for older COSMIC."""
    own = config_dir() / f"cosmic/com.system76.CosmicBackground.{mode.capitalize()}/v1"
    return own if own.is_dir() else shared_wallpaper_folder()


def shared_wallpaper_folder() -> Path:
    return config_dir() / "cosmic/com.system76.CosmicBackground/v1"


def seed_wallpaper(folder: Path) -> None:
    """Fill a mode's empty wallpaper folder from the shared one, as cosmic-bg does when it starts."""
    shared = shared_wallpaper_folder()
    if folder == shared or (folder / "all").is_file() or not (shared / "all").is_file():
        return
    for key in ("all", "same-on-all"):
        if (shared / key).is_file() and not (folder / key).is_file():
            shutil.copyfile(shared / key, folder / key)


def active(rices: list[Rice]) -> Rice | None:
    link = Path.home() / "update_system.sh"
    if not link.is_symlink():
        return None
    repo = Path(os.readlink(link)).parent.parent
    return next((r for r in rices if r.repo == repo), None)


def value(path: Path) -> str:
    """A COSMIC string setting without the quotes it is stored with."""
    return path.read_text().replace('"', "").replace("\n", "") if path.is_file() else ""


def backup(path: Path) -> None:
    """Copy path to path.bak, never more readable than the original: ~/.zshrc can hold secrets."""
    bak = path.with_name(path.name + ".bak")
    bak.unlink(missing_ok=True)
    with os.fdopen(os.open(bak, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as out, path.open("rb") as src:
        shutil.copyfileobj(src, out)
    shutil.copymode(path, bak)


def backup_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        backup(dest)
    shutil.copyfile(src, dest)


def has_tool(rice: Rice, tool: str) -> bool:
    return os.access(rice.repo / tool / "install.sh", os.X_OK)


def install(rice: Rice, tool: str) -> bool:
    """Run <tool>/install.sh if the rice has one, showing its output under the tool's name."""
    if not has_tool(rice, tool):
        return True
    done = subprocess.run([f"./{tool}/install.sh"], cwd=rice.repo, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, text=True)
    for line in done.stdout.splitlines():
        if line:
            print(f"  {tool}: {line}")
    return done.returncode == 0


def icons_installed(name: str) -> bool:
    roots = (Path.home() / ".local/share/icons", Path("/usr/share/icons"))
    return any((root / name).is_dir() for root in roots)


def stored_schemes(rice: Rice) -> Path:
    return config_dir() / f"cosmic/com.system76.CosmicTerm/v1/color_schemes_{rice.mode}"


def missing_scheme(rice: Rice) -> Path | None:
    """The rice's terminal scheme file, if COSMIC Terminal does not have it yet."""
    scheme = rice.repo / "cosmic-term" / rice.term_ron
    if not scheme.is_file():
        return None
    name = re.search(r'name: "([^"]*)"', scheme.read_text())
    stored = stored_schemes(rice)
    known = stored.read_text() if stored.is_file() else ""
    return scheme if name and f'name: "{name.group(1)}"' not in known else None


def add_scheme(rice: Rice) -> None:
    """COSMIC Terminal only looks a scheme up in its own list. Without it there, open
    tabs keep the last rice's colours and new ones use the default."""
    scheme = missing_scheme(rice)
    if scheme is None:
        return
    stored = stored_schemes(rice)
    text = stored.read_text().strip() if stored.is_file() else "{}"
    if not (text.startswith("{") and text.endswith("}")):
        print(f"  cosmic: could not read {stored.name}, import {scheme.name} by hand")
        return
    ids = [int(number) for number in re.findall(r"^\s*(\d+)\s*:", text, re.M)]
    body = text[:-1].rstrip()
    if body != "{" and not body.endswith(","):
        body += ","
    entry = scheme.read_text().strip().replace("\n", "\n    ")
    stored.parent.mkdir(parents=True, exist_ok=True)
    if stored.is_file():
        backup(stored)
    stored.write_text(f"{body}\n    {max(ids, default=-1) + 1}: {entry},\n}}\n")
    print(f"  cosmic: added terminal scheme {scheme.name}")


def apply_cosmic(rice: Rice, keep_icons: bool) -> None:
    """Fonts, terminal look, icons. A terminal scheme or icon theme that is already
    a variant of this rice's stays, so dimmed and recoloured choices survive."""
    other = "light" if rice.mode == "dark" else "dark"
    source = rice.repo / "cosmic/config"
    add_scheme(rice)
    for src in sorted(p for p in source.rglob("*") if p.is_file()):
        rel = src.relative_to(source)
        dest = config_dir() / "cosmic" / rel
        want, have = value(src), value(dest)
        if src.name == f"syntax_theme_{other}":
            continue
        if src.name == f"syntax_theme_{rice.mode}" and (have == want or have.startswith(want + " ")):
            print(f"  cosmic: terminal scheme stays {have}")
            continue
        if src.name == "icon_theme":
            have = icons_in_use()
            stay = (" (--keep-icons)" if keep_icons
                    else "" if have.startswith(want.rsplit("-", 1)[0] + "-")
                    else f", {want} is not installed (./icons/install.sh)" if not icons_installed(want)
                    else None)
            if stay is not None:
                print(f"  cosmic: icons stay {have or 'default'}{stay}")
                if have and have != value(dest):  # CosmicTk is what flip puts back after the import
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.is_file():
                        backup(dest)
                    dest.write_text(f'"{have}"')
                set_theme_icons(rice.mode, have)
                continue
            set_theme_icons(rice.mode, want)
        backup_copy(src, dest)
        print(f"  cosmic: {rel}")
    mode_file().parent.mkdir(parents=True, exist_ok=True)
    mode_file().write_text("true\n" if rice.mode == "dark" else "false\n")
    print(f"  cosmic: {rice.mode} mode")


def apply_btop(rice: Rice) -> None:
    themes = config_dir() / "btop/themes"
    themes.mkdir(parents=True, exist_ok=True)
    shutil.copy(rice.repo / f"btop/{rice.btop}.theme", themes)
    conf = config_dir() / "btop/btop.conf"
    if not conf.is_file():
        print("  btop: theme copied, pick it in btop (Esc → Options → Color theme)")
        return
    backup(conf)
    conf.write_text(re.sub(r"^color_theme = .*$", f'color_theme = "{rice.btop}"', conf.read_text(), flags=re.M))
    print(f"  btop: {rice.btop}")


def park_nvim(rice: Rice, rices: list[Rice]) -> None:
    plugins = config_dir() / "nvim/lua/plugins"
    parked = config_dir() / "nvim/rice-off"
    for slug in [r.slug for r in rices] + list(LEGACY_NVIM):
        spec = plugins / f"{slug}.lua"
        if slug != rice.slug and spec.is_file():
            parked.mkdir(parents=True, exist_ok=True)
            spec.replace(parked / spec.name)
            print(f"  nvim: {spec.name} -> rice-off/")


def apply_zsh(rice: Rice) -> bool:
    """Comment out every other rice's source line, uncomment this one, or add it."""
    rc = Path.home() / ".zshrc"
    rc.touch()
    backup(rc)
    own = f"cosmic-{rice.slug}-theme/zsh/{rice.slug}.zsh"
    lines = []
    for line in rc.read_text().splitlines(keepends=True):
        if ZSH_ANY.match(line):
            if own in line:
                line = re.sub(r"^(\s*)#\s*", r"\1", line)
            else:
                line = re.sub(r"^(\s*)([^#\s])", r"\1# \2", line)
        lines.append(line)
    rc.write_text("".join(lines))
    ok = True
    if not any(own in x and not x.lstrip().startswith("#") for x in lines):
        ok = install(rice, "zsh")
        if not ok:
            print("  zsh: install.sh failed, see above")
    print("  zsh: active rice lines:")
    live = [(n, x.rstrip("\n")) for n, x in enumerate(rc.read_text().splitlines(keepends=True), 1)
            if ZSH_ANY.match(x) and not x.lstrip().startswith("#")]
    for n, x in live or [(0, "none")]:
        print(f"    {n}:{x}" if n else "    none")
    return ok


def print_steps(rice: Rice) -> None:
    r = rice.repo
    Mode = rice.mode.capitalize()
    steps = [f"Settings → Desktop → Appearance → {Mode} → Import cosmic/{rice.ron}"]
    if missing_scheme(rice):
        steps.append(f"COSMIC Terminal → View → Color schemes → {Mode} tab → Import cosmic-term/{rice.term_ron}")
    if has_tool(rice, "firefox"):
        steps.append("Firefox: enable this rice's add-on in about:addons (link in the README), restart Firefox")
    if has_tool(rice, "claude-desktop"):
        jsonc = sorted((r / "claude-desktop").glob("*.jsonc"))
        claude = jsonc[0].stem if jsonc else "this rice's theme"
        steps.append(f"Claude Desktop: Ctrl+Shift+T → {claude}, Appearance → {Mode}")
    shell = [text for tool, text in (("zsh", "exec zsh"), ("nvim", "restart Neovim")) if has_tool(rice, tool)]
    if shell:
        steps.append(", ".join(shell))
    print(f"\n{rice.name} is active. Left to do by hand (skip what is already done), paths under {r}:")
    for number, step in enumerate(steps, 1):
        print(f"  {number}. {step}")
    if has_tool(rice, "cursors"):
        print("  Cursor (optional, sudo + reboot): ./cursors/install.sh")
    for tg in sorted(r.glob("telegram/*.tdesktop-theme")):
        print(f"  Telegram (optional): Settings → Chat Settings → Chat wallpaper → Choose from file → {tg.relative_to(r)}")
    if (r / "brave/theme/manifest.json").is_file():
        print(f"  Brave (optional): brave://extensions → Developer mode → Load unpacked → {r}/brave/theme")
    if has_tool(rice, "obsidian"):
        print("  Obsidian (optional): ./obsidian/install.sh <vault>, then Settings → Appearance → CSS snippets")
    if has_tool(rice, "helix") or has_tool(rice, "kitty"):
        print("  Terminals and editors: the installers above only copy theme files; see the README for")
        print("  the one include line each of kitty, Alacritty, WezTerm, Ghostty, Helix, delta and qt6ct needs")


def switch(rice: Rice, rices: list[Rice], keep_icons: bool = False, steps: bool = True) -> bool:
    """Make a rice active. A failed tool does not stop the others; returns False if any failed."""
    print(f"Switching to {rice.name}")
    failed = []
    apply_cosmic(rice, keep_icons)
    for tool in TOOLS:
        if not install(rice, tool):
            failed.append(tool)
    if rice.btop:
        try:
            apply_btop(rice)
        except OSError as err:
            print(f"  btop: {err}")
            failed.append("btop")
    if has_tool(rice, "nvim"):
        if not install(rice, "nvim"):
            failed.append("nvim")
        park_nvim(rice, rices)
    if has_tool(rice, "zsh") and not apply_zsh(rice):
        failed.append("zsh")
    link = Path.home() / "update_system.sh"
    if link.is_file() and not link.is_symlink():
        backup(link)
    link.unlink(missing_ok=True)
    link.symlink_to(rice.repo / "scripts/update_system.sh")
    print(f"  ~/update_system.sh -> {rice.name}")
    if not install(rice, "firefox"):
        print("  firefox: skipped (see above)")
    if not install(rice, "claude-desktop"):
        failed.append("claude-desktop")
    if steps:
        print_steps(rice)
    if failed:
        print(f"\nThese failed, see above: {', '.join(failed)}")
    return not failed


def fetch(repos: Path, name: str) -> bool:
    """Clone one rice repo. False if it was already here."""
    target = repos / name
    if target.is_dir():
        print(f"{name} is already here")
        return False
    print(f"Downloading {name}")
    repos.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--", f"{SOURCE}/{name}", str(target)],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if done.returncode:
        raise Error(f"could not download {name}: is that a rice? See {GALLERY}")
    return True


def get(repos: Path, wanted: str) -> None:
    """Download a rice and its other half."""
    slug = wanted.lower().replace(" ", "")
    if not re.fullmatch(r"[a-z0-9]+", slug):
        raise Error(f"{wanted!r} is not a rice name, see {GALLERY}")
    name = f"cosmic-{slug}-theme"
    fetch(repos, name)
    other = pair_repo(repos / name)
    if other:
        fetch(repos, other)
    print(f"Done. Next: themebox switch {slug}")


def choice_file() -> Path:
    return config_dir() / "themebox/choice"


def chosen_pair(rices: list[Rice]) -> tuple[Rice, Rice] | None:
    """The two rices picked with themebox choose, if both still exist."""
    path = choice_file()
    slugs = path.read_text().split() if path.is_file() else []
    found = [r for s in slugs for r in rices if r.slug == s]
    return (found[0], found[1]) if len(found) == 2 else None


def choose(rices: list[Rice], first: str, second: str) -> None:
    a, b = find(rices, first), find(rices, second)
    if a.mode == b.mode:
        raise Error(f"pick one dark and one light rice: {a.slug} and {b.slug} are both {a.mode}")
    choice_file().parent.mkdir(parents=True, exist_ok=True)
    choice_file().write_text(f"{a.slug} {b.slug}\n")


def reset_choice() -> None:
    choice_file().unlink(missing_ok=True)


def partner(rice: Rice, rices: list[Rice]) -> Rice | None:
    """Where a flip goes from this rice: the chosen other half, else its own pair."""
    chosen = chosen_pair(rices)
    if chosen and rice.slug in (chosen[0].slug, chosen[1].slug):
        return chosen[1] if rice.slug == chosen[0].slug else chosen[0]
    return find(rices, rice.pair) if rice.pair else None


def follow(rices: list[Rice], keep_icons: bool = False) -> Rice | None:
    """Move to the other half if COSMIC's mode no longer matches. Returns the rice moved to."""
    current = active(rices)
    if current is None:
        raise Error("no active rice: run themebox switch <slug> once first")
    state = value(mode_file())
    if state not in ("true", "false") or ("dark" if state == "true" else "light") == current.mode:
        return None
    target = partner(current, rices)
    if target is None:
        raise Error(f"{current.name} has no pair")
    switch(target, rices, keep_icons, steps=False)
    return target


def run_quiet(cmd: list[str], timeout: float = 30) -> bool:
    """Run a desktop command, True if it worked. Never raises."""
    try:
        done = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def apply_theme(rice: Rice) -> list[str]:
    """Import the COSMIC theme, which also sets the desktop's light or dark mode."""
    path = rice.repo / "cosmic" / rice.ron
    if run_quiet(["cosmic-settings", "appearance", "import", str(path)]):
        return []
    return [f"{FAILED} theme import, in Settings → Desktop → Appearance import {path}"]


def backgrounds(rice: Rice) -> list[Path]:
    return sorted(p for p in (rice.repo / "backgrounds").glob("*") if p.is_file())


def short_name(rice: Rice, path: Path) -> str:
    return path.stem.removeprefix(f"{rice.slug}-")


def find_wallpaper(rice: Rice, wanted: str) -> Path | None:
    for path in backgrounds(rice):
        if wanted in (path.name, path.stem, short_name(rice, path)):
            return path
    return None


def memory_file(rice: Rice) -> Path:
    return choice_file().parent / "wallpapers" / rice.slug


def remember(rice: Rice, wallpaper: str) -> None:
    memory_file(rice).parent.mkdir(parents=True, exist_ok=True)
    memory_file(rice).write_text(wallpaper)


def remembered(rice: Rice) -> Path | None:
    path = memory_file(rice)
    return Path(path.read_text()) if path.is_file() else None


def desktop_wallpaper(mode: str | None = None) -> str | None:
    """The wallpaper on all monitors in a mode, the one showing now by default."""
    entry = wallpaper_folder(mode or current_mode()) / "all"
    if not entry.is_file():
        entry = shared_wallpaper_folder() / "all"  # cosmic-bg has not seeded this mode yet
    found = WALLPAPER.search(entry.read_text()) if entry.is_file() else None
    return found.group(1).replace("\\\\", "\\") if found else None


def pick_wallpaper(rice: Rice) -> Path | None:
    """The default: the rice's anime wallpaper, else its first file."""
    anime = rice.repo / "backgrounds" / f"{rice.slug}-anime.png"
    if anime.is_file():
        return anime
    files = backgrounds(rice)
    return files[0] if files else None


def apply_wallpaper(rice: Rice, previous: Rice | None, chosen: Path | None = None) -> list[str]:
    """Change only the path in cosmic-bg's entry for all monitors, in the rice's mode.

    Uses chosen if given, else what this rice last had, else its default.
    Staying on the same rice keeps the wallpaper unless one was chosen.
    """
    folder = wallpaper_folder(rice.mode)
    seed_wallpaper(folder)
    manual = f"Wallpaper: Settings → Wallpaper → a file from {rice.repo}/backgrounds"
    entry = folder / "all"
    if value(folder / "same-on-all") == "false" or not entry.is_file():
        return [manual]
    text = entry.read_text()
    if WALLPAPER.search(text) is None:
        return [manual]
    if chosen is None and previous == rice:
        return []
    left = desktop_wallpaper(previous.mode) if previous else None
    if previous and left:
        remember(previous, left)
    kept = remembered(rice)
    chosen = chosen or (kept if kept and kept.is_file() else pick_wallpaper(rice))
    if chosen is None:
        return []
    escaped = str(chosen).replace("\\", "\\\\").replace('"', '\\"')
    backup(entry)
    entry.write_text(WALLPAPER.sub(lambda _: f'source: Path("{escaped}")', text, count=1))
    return []


def save_wallpaper(rice: Rice, path: Path, is_active: bool) -> list[str]:
    """Keep this wallpaper for the rice, and show it now if the rice is active."""
    remember(rice, str(path))
    return apply_wallpaper(rice, None, path) if is_active else []


def print_wallpapers(rice: Rice, is_active: bool) -> None:
    """The rice's wallpapers by short name, * marks the one in use or saved."""
    marked = desktop_wallpaper(rice.mode) if is_active else remembered(rice)
    for path in backgrounds(rice):
        print(f"{'*' if str(path) == str(marked) else ' '} {short_name(rice, path)}")


def ask_wallpaper(rice: Rice) -> Path | None:
    """Prompt for one of the rice's wallpapers. None keeps the saved one."""
    files = backgrounds(rice)
    if not files:
        return None
    print(f"Wallpapers for {rice.name}:")
    for number, path in enumerate(files, 1):
        print(f"  {number}. {short_name(rice, path)}")
    while True:
        try:
            answer = input("Number or name, Enter keeps the saved one: ").strip()
        except EOFError:
            raise Error("--pick needs a terminal") from None
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(files):
            return files[int(answer) - 1]
        found = find_wallpaper(rice, answer)
        if found:
            return found
        print(f"No wallpaper {answer}")


def stored_theme(mode: str) -> dict[str, str]:
    """COSMIC's theme settings, one file per field, from its newest version folder."""
    newest = theme_folder(mode, builder=True)
    files = newest.iterdir() if newest else ()
    return {p.name: p.read_text().strip() for p in files if p.is_file() and re.fullmatch(r"[a-z0-9_]+", p.name)}


def theme_ron(mode: str, name: str) -> str:
    """The stored theme as one file that cosmic-settings can import."""
    fields = {**dict.fromkeys(THEME_COLORS, "None"), **stored_theme(mode)}
    missing = [field for field in THEME_NEEDED if field not in fields]
    if missing:
        raise Error(f"COSMIC has not stored a whole {mode} theme (no {', '.join(missing)}): "
                    "import one, or use Export in Settings → Desktop → Appearance")
    fields["palette"] = re.sub(r'name: "(?:[^"\\]|\\.)*"', f'name: "{name}"', fields["palette"], count=1)
    body = "".join(f"    {field}: {fields[field].replace(chr(10), chr(10) + '    ')},\n" for field in sorted(fields))
    return f"(\n{body})\n"


def copy_wallpaper(repo: Path, slug: str, mode: str) -> str | None:
    """Copy the desktop's wallpaper into repo/backgrounds. Its file name, None if there is no one file."""
    folder = wallpaper_folder(mode)
    current = desktop_wallpaper(mode)
    if value(folder / "same-on-all") == "false" or current is None or not Path(current).is_file():
        return None
    copied = repo / "backgrounds" / f"{slug}-{Path(current).name}"
    copied.parent.mkdir()
    shutil.copyfile(current, copied)
    return copied.name


def capture(repos: Path, wanted: str) -> None:
    """Save the current look as a new rice. It lands whole or not at all."""
    name = wanted.strip(" ")
    slug = name.lower().replace(" ", "")
    if not re.fullmatch(r"[a-z0-9]+", slug):
        raise Error(f"{wanted!r} is not a rice name: use letters, digits and spaces")
    target = repos / f"cosmic-{slug}-theme"
    if target.exists():
        raise Error(f"{target} already exists, pick another name")
    mode = current_mode()
    ron = f"{name.replace(' ', '')}.ron"
    theme = theme_ron(mode, name)
    stored = stored_theme(mode)
    repos.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=repos, prefix=".capture-") as tmp:
        build = Path(tmp) / "rice"
        (build / "cosmic").mkdir(parents=True)
        (build / "cosmic" / ron).write_text(theme)
        for setting in TK_LOOK:
            live = config_dir() / "cosmic/com.system76.CosmicTk/v1" / setting
            saved = build / "cosmic/config/com.system76.CosmicTk/v1" / setting
            in_theme = stored.get(THEME_LOOK.get(setting, ""))  # newer COSMIC keeps these in the theme
            if in_theme is not None or live.is_file():
                saved.parent.mkdir(parents=True, exist_ok=True)
            if in_theme is not None:
                saved.write_text(in_theme)
            elif live.is_file():
                shutil.copyfile(live, saved)
        wallpaper = copy_wallpaper(build, slug, mode)
        (build / "rice.toml").write_text(f'name = "{name}"\nmode = "{mode}"\ntheme = "{ron}"\n')
        build.rename(target)
    print(f"Saved the current {mode} theme as {name} in {target}")
    if wallpaper:
        print(f"  backgrounds/{wallpaper}")
    else:
        print(f"  Wallpaper: not a single image, so none was copied. Add one to {target}/backgrounds")
    print(f"Next: themebox switch {slug}")


def leftovers(rice: Rice) -> list[str]:
    """What COSMIC and the apps only allow by hand."""
    steps = []
    if has_tool(rice, "firefox"):
        steps.append(f"Firefox: enable the {rice.name} add-on in about:addons, then restart Firefox")
    wanted = value(rice.repo / "cosmic/config/com.system76.CosmicTk/v1/icon_theme")
    if wanted and not icons_installed(wanted):
        steps.append(f"Icons: {wanted} is not installed, run {rice.repo}/icons/install.sh")
    scheme = missing_scheme(rice)
    if scheme:
        steps.append(f"COSMIC Terminal: View → Color schemes → {rice.mode.capitalize()} tab → Import {scheme}")
    return steps


def nvim_sockets() -> list[Path]:
    """Every running Neovim's default socket for this user."""
    run = os.environ.get("XDG_RUNTIME_DIR")
    return sorted(p for p in Path(run).rglob("nvim.*") if not p.is_dir()) if run else []


def reload_nvim(rice: Rice) -> list[str]:
    """Recolour running Neovims. One that has gone away just fails quietly."""
    colors = sorted((rice.repo / "nvim/colors").glob("*.lua"))
    if colors:
        expr = f"execute('colorscheme {colors[0].stem}')"
        for sock in nvim_sockets():
            run_quiet(["nvim", "--server", str(sock), "--remote-expr", expr], timeout=5)
    return []


def shell_line() -> str:
    return f'source "{Path(__file__).resolve().parent}/zsh/reload.zsh"'


def install_shell() -> bool:
    """Add the reload snippet to ~/.zshrc. False if it is already there."""
    rc = Path.home() / ".zshrc"
    rc.touch()
    text = rc.read_text()
    if "zsh/reload.zsh" in text:
        return False
    backup(rc)
    rc.write_text(text + ("" if text.endswith("\n") or not text else "\n") + shell_line() + "\n")
    return True


def reload_zsh() -> list[str]:
    """Signal registered shells only: USR1 kills a zsh that has no trap for it."""
    rc = Path.home() / ".zshrc"
    if "zsh/reload.zsh" not in (rc.read_text() if rc.is_file() else ""):
        return ["Open zsh shells: run themebox install-shell once, or exec zsh in each"]
    run = os.environ.get("XDG_RUNTIME_DIR")
    folder = Path(run) / "themebox/zsh" if run else None
    for entry in sorted(folder.iterdir()) if folder and folder.is_dir() else []:
        if not entry.name.isdigit():
            continue
        try:
            is_zsh = (Path("/proc") / entry.name / "comm").read_text().strip() == "zsh"
            if is_zsh:
                os.kill(int(entry.name), signal.SIGUSR1)
        except OSError:
            is_zsh = False
        if not is_zsh:
            entry.unlink(missing_ok=True)
    return []


def report(rice: Rice, messages: list[str]) -> None:
    print(f"\n{rice.name} is active.")
    if messages:
        print("Left to do:")
        for m in messages:
            print(f"  {m}")
    if shutil.which("notify-send"):
        body = "\n".join(messages) or "Nothing left to do."
        run_quiet(["notify-send", "--app-name=themebox", f"{rice.name} is active", body])


def flip(rices: list[Rice], keep_icons: bool = False, pick: bool = False) -> bool:
    """Move to the other half and change everything live. False if any step failed."""
    current = active(rices)
    if current is None:
        raise Error("no active rice: run themebox switch <slug> once first")
    target = partner(current, rices)
    if target is None:
        raise Error(f"{current.name} has no pair")
    chosen = ask_wallpaper(target) if pick else None
    return go_live(target, current, rices, keep_icons, chosen)


def go_live(target: Rice, current: Rice | None, rices: list[Rice], keep_icons: bool, chosen: Path | None) -> bool:
    """Make target active and change everything live. False if any step failed."""
    # switch comes first so a running pair --watch already sees the new half
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        switched = switch(target, rices, keep_icons, steps=False)
    if not switched:
        print(log.getvalue())
    messages = [] if switched else [f"{FAILED} some tools, run themebox flip in a terminal to see which"]
    messages += apply_theme(target)
    # the import sets the icons the .ron names; put back the ones switch chose
    set_theme_icons(target.mode, value(config_dir() / "cosmic/com.system76.CosmicTk/v1/icon_theme"))
    messages += apply_wallpaper(target, current, chosen) + reload_nvim(target)
    if has_tool(target, "zsh"):
        messages += reload_zsh()
    messages += leftovers(target)
    report(target, messages)
    return not any(m.startswith(FAILED) for m in messages)


def print_list(rices: list[Rice]) -> None:
    current = active(rices)
    for r in sorted(rices, key=lambda r: r.slug):
        mark = "*" if r is current else " "
        print(f"{mark} {r.slug:<16}{r.name:<17}{r.mode:<7}{r.pair or '-'}")
    chosen = chosen_pair(rices)
    if chosen:
        print(f"\nflip goes between {chosen[0].slug} and {chosen[1].slug}")


def palette(rice: Rice) -> list[tuple[str, str, str]]:
    """A rice's colours as (role, #HEX, name): the README table the gallery reads too."""
    readme = rice.repo / "README.md"
    text = readme.read_text() if readme.is_file() else ""
    section = text.split("## Palette", 1)[1].split("\n## ", 1)[0] if "## Palette" in text else ""
    start = section.find("| Role")
    colours: dict[str, tuple[str, str, str]] = {}
    # the first table is the palette, a later one compares the pair
    for role, code, label in COLOUR_ROW.findall(section[start:].split("\n\n", 1)[0] if start >= 0 else ""):
        code = f"#{code.upper()}"
        colours.setdefault(code, (role, code, re.sub(r"!\[[^\]]*\]\([^)]*\)", "", label).strip()))
    return list(colours.values())


def icon_colours(pack: str) -> list[tuple[str, str, str]]:
    """An icon pack's colours, from the table that tools/icon_palettes.py writes."""
    table = Path(__file__).resolve().parent / "icon-palettes.toml"
    colours: dict[str, tuple[str, str, str]] = {}
    for role, code in (tomllib.loads(table.read_text()).get(pack, {}) if table.is_file() else {}).items():
        colours.setdefault(code, (role, code, ""))
    return list(colours.values())


def cursor_colours(theme: Path) -> list[tuple[str, str, str]]:
    """A cursor's rim, body and gloss, read from the pixels of its arrow at its largest size."""
    try:
        data = (theme / "cursors/left_ptr").read_bytes()
        header, _, count = struct.unpack_from("<III", data, 4)
        chunks = [struct.unpack_from("<III", data, header + i * 12) for i in range(count)]
        _, _, start = max(chunk for chunk in chunks if chunk[0] == XCURSOR_IMAGE)
        width, height = struct.unpack_from("<II", data, start + 16)
        pixels = struct.iter_unpack("BBBB", data[start + 36:start + 36 + width * height * 4])
        # the border and outline are the same white and black on every cursor
        solid = sorted((r + g + b, f"#{r:02X}{g:02X}{b:02X}") for b, g, r, a in pixels if a == 255 and 15 < r + g + b < 750)
    except (OSError, ValueError, struct.error):
        return []
    if not solid:
        return []
    return [(role, solid[int((len(solid) - 1) * place)][1], "")
            for role, place in (("Rim", .05), ("Body", .5), ("Gloss", .95))]


def variants(rice: Rice, tool: str) -> list[str]:
    """The colours a rice's cursor or icon installer offers.

    Read from the script as text, never by running it: browsing must not run a rice's code.
    """
    script = rice.repo / tool / "install.sh"
    found = VARIANT_LIST.search(script.read_text(errors="replace")) if has_tool(rice, tool) else None
    names = found.group(1).split() if found else []
    return names if all(re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in names) else []


def cursor_in_use() -> str:
    """The cursor theme set for the next login."""
    env = Path("/etc/environment")
    found = re.search(r"^XCURSOR_THEME=(.*)$", env.read_text(), re.M) if env.is_file() else None
    return found.group(1).strip("\"' ") if found else ""


def icons_in_use() -> str:
    """The icon theme showing now: the theme's own on COSMIC after 1.11.0, else CosmicTk's."""
    entry = theme_icons(current_mode()) or config_dir() / "cosmic/com.system76.CosmicTk/v1/icon_theme"
    return value(entry)


def cursor_name(rice: Rice, variant: str) -> str:
    return next((p.name for p in (rice.repo / "cursors").glob(f"*-{variant}") if p.is_dir()), "")


def icon_name(rice: Rice, variant: str) -> str:
    default = value(rice.repo / "cosmic/config/com.system76.CosmicTk/v1/icon_theme")
    return f"{default.rsplit('-', 1)[0]}-{variant}" if default else ""


def run_installer(rice: Rice, tool: str, variant: str) -> bool:
    """Run a cursor or icon installer on the terminal, so sudo can ask for a password."""
    print(f"\n{tool.capitalize()}: {variant}")
    return subprocess.run([f"./{tool}/install.sh", "--variant", variant], cwd=rice.repo).returncode == 0


class Choices:
    """What the screen has picked so far. A field left None keeps what is there now."""

    def __init__(self, rices: list[Rice]):
        self.rices = sorted(rices, key=lambda r: r.slug)
        self.current = active(rices)
        self.rice = self.current
        self.wallpaper: Path | None = None
        self.cursor: str | None = None
        self.icons: str | None = None
        chosen = chosen_pair(rices) or ()
        self.saved_pair = (next((r.slug for r in chosen if r.mode == "dark"), None),
                           next((r.slug for r in chosen if r.mode == "light"), None))
        self.dark, self.light = self.saved_pair
        self.cached: dict[tuple[str, str], list[str]] = {}
        self.palettes: dict[str, list[tuple[str, str, str]]] = {}

    def colours(self, rice: Rice) -> list[tuple[str, str, str]]:
        return self.palettes.setdefault(rice.slug, palette(rice))

    def option_colours(self, tab: str, option: str) -> list[tuple[str, str, str]]:
        """The colours of one cursor or icon option. Empty if they are not known."""
        key = f"{self.rice.slug}/{tab}/{option}"
        if key not in self.palettes:
            self.palettes[key] = (icon_colours(icon_name(self.rice, option)) if tab == "Icons" else
                                  cursor_colours(self.rice.repo / "cursors" / cursor_name(self.rice, option)))
        return self.palettes[key]

    def panel(self, tab: str, option: object) -> tuple[str, list[tuple[str, str, str]]] | None:
        """The title and colours for the row under the cursor. Keep current means what is in use."""
        if tab == "Rice":
            return (option.name, self.colours(option)) if option else None
        if self.rice is None:
            return None
        option = option or next((row[0] for row in self.rows(tab) if row[2] == "in use"), None)
        colours = self.option_colours(tab, option) if option else []
        return (option, colours) if colours else (self.rice.name, self.colours(self.rice))

    def pair_shown(self, side: str, slug: str | None) -> Rice | None:
        """The rice to show under a Pair column: the cursor's row, else what flip would use now."""
        slug = slug or self.selected("Pair", side)
        if slug:
            return find(self.rices, slug)
        if self.current is None or self.current.mode == side:
            return self.current
        return partner(self.current, self.rices)

    def options(self, tool: str) -> list[str]:
        key = (self.rice.slug if self.rice else "", tool)
        if key not in self.cached:
            self.cached[key] = variants(self.rice, tool) if self.rice else []
        return self.cached[key]

    def rows(self, tab: str, side: str = "dark") -> list[tuple[object, str, str]]:
        """One tab's rows as (value, label, note). Column side is for the Pair tab."""
        rice = self.rice
        if tab == "Rice":
            return [(r, f"{r.name:<18}{r.mode:<7}", "active" if r == self.current else "") for r in self.rices]
        if tab == "Pair":
            return [(None, "Each rice's own pair", "")] + [(r.slug, r.name, "") for r in self.rices if r.mode == side]
        if rice is None:
            return []
        if tab == "Wallpaper":
            live = rice == self.current
            marked = desktop_wallpaper(rice.mode) if live else remembered(rice)
            return [(None, "Keep current" if live else "Saved or default", "")] + [
                (path, short_name(rice, path), "in use" if live and str(path) == str(marked)
                 else "saved" if str(path) == str(marked) else "") for path in backgrounds(rice)]
        if tab == "Cursors":
            now = cursor_in_use()
            return [(None, "Keep current", now)] + [
                (v, v, "in use" if now and cursor_name(rice, v) == now else "") for v in self.options("cursors")]
        now = icons_in_use()
        return [(None, "Keep current", now)] + [
            (v, v, "in use" if icon_name(rice, v) == now else "installed" if icons_installed(icon_name(rice, v))
             else "downloads") for v in self.options("icons")]

    def selected(self, tab: str, side: str = "dark") -> object:
        return {"Rice": self.rice, "Wallpaper": self.wallpaper, "Cursors": self.cursor, "Icons": self.icons,
                "Pair": self.dark if side == "dark" else self.light}[tab]

    def pick(self, tab: str, picked: object, side: str = "dark") -> None:
        if tab == "Rice":
            if picked != self.rice:
                self.rice, self.wallpaper, self.cursor, self.icons = picked, None, None, None
        elif tab == "Wallpaper":
            self.wallpaper = picked
        elif tab == "Cursors":
            self.cursor = picked
        elif tab == "Icons":
            self.icons = picked
        elif picked is None:
            self.dark = self.light = None
        else:
            self.pick_half(picked, side)

    def pick_half(self, slug: str, side: str) -> None:
        """Set one half of the pair. An empty other half starts as this rice's own pair."""
        if side == "dark":
            self.dark = slug
            self.light = self.light or find(self.rices, slug).pair
        else:
            self.light = slug
            self.dark = self.dark or find(self.rices, slug).pair

    def pair_changed(self) -> bool:
        return (self.dark, self.light) != self.saved_pair

    def pending(self) -> list[str]:
        """What Apply would do, in words."""
        changes = []
        if self.rice and self.rice != self.current:
            changes.append(f"switch to {self.rice.name}")
        if self.wallpaper:
            changes.append(f"wallpaper {short_name(self.rice, self.wallpaper)}")
        if self.pair_changed():
            changes.append(f"flip {self.dark} and {self.light}" if self.dark and self.light else "flip own pairs")
        if self.cursor:
            changes.append(f"cursor {self.cursor}")
        if self.icons:
            changes.append(f"icons {self.icons}")
        return changes

    def problem(self) -> str | None:
        if bool(self.dark) != bool(self.light):
            return f"Pair: pick a {'light' if self.dark else 'dark'} rice too"
        return None


def apply_choices(c: Choices) -> bool:
    """Do what was picked, on the plain terminal. False if any step failed."""
    ok = True
    if c.pair_changed():
        if c.dark:
            choose(c.rices, c.dark, c.light)
            print(f"flip goes between {c.dark} and {c.light}")
        else:
            reset_choice()
            print("flip uses each rice's own pair")
    if c.rice and c.rice != c.current:
        ok = go_live(c.rice, c.current, c.rices, True, c.wallpaper)  # the Icons tab decides the icons
    elif c.wallpaper:
        for message in save_wallpaper(c.rice, c.wallpaper, True):
            print(f"  {message}")
    if c.icons:
        ok = run_installer(c.rice, "icons", c.icons) and ok
    if c.cursor:
        ok = run_installer(c.rice, "cursors", c.cursor) and ok
    return ok


class Screen:
    """The tabs. It only fills in a Choices: the work happens after curses has closed."""
    TABS = ("Rice", "Wallpaper", "Pair", "Cursors", "Icons")
    SIDES = ("dark", "light")

    def __init__(self, scr, choices: Choices):
        self.scr, self.c = scr, choices
        self.tab = 0
        self.side = 0  # which Pair column has the cursor
        here = choices.rices.index(choices.current) if choices.current else 0
        self.at: dict[tuple[str, str], int] = {("Rice", "dark"): here}  # the cursor row of each list
        self.top: dict[tuple[str, str], int] = {}
        self.hits: list[tuple[int, int, int, tuple]] = []  # y, x from, x to, what a click there does
        self.blocks: list[tuple[int, int, int, str]] = []  # y, x, width, #HEX of each colour block
        self.status = ""
        self.colors = curses.has_colors() and not os.environ.get("NO_COLOR")
        if self.colors:
            curses.start_color()
            try:
                curses.use_default_colors()
                back = -1
            except curses.error:
                back = curses.COLOR_BLACK
            curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_BLUE)  # from the terminal's palette, so it matches
            curses.init_pair(2, curses.COLOR_BLUE, back)
            curses.init_pair(3, curses.COLOR_RED, back)
        with contextlib.suppress(curses.error):
            curses.curs_set(0)
        scr.keypad(True)
        curses.mousemask(curses.ALL_MOUSE_EVENTS)
        curses.mouseinterval(0)  # report a press at once rather than waiting to see if it is a click

    def bar(self) -> int:
        return curses.color_pair(1) if self.colors else curses.A_REVERSE

    def tint(self, pair: int) -> int:
        return curses.color_pair(pair) if self.colors else curses.A_BOLD

    def put(self, y: int, x: int, text: str, attr: int = 0, click: tuple | None = None) -> None:
        h, w = self.scr.getmaxyx()
        if not (0 <= y < h and 0 <= x < w - 1):
            return
        text = text[:w - x - 1]
        with contextlib.suppress(curses.error):
            self.scr.addstr(y, x, text, attr)
        if click:
            self.hits.append((y, x, x + len(text), click))

    def block(self, y: int, x: int, width: int, code: str) -> None:
        """Mark cells for a colour. curses has no 24-bit colours, so paint_blocks fills them in.

        curses gets a stand-in character so it knows the cells are in use, and clears them when
        the block goes. If it thought they were empty, a block would stay on screen for good.
        """
        h, w = self.scr.getmaxyx()
        width = min(width, w - x - 1)
        if not self.colors or not (0 <= y < h) or width <= 0:
            return
        self.put(y, x, "#" * width)
        self.blocks.append((y, x, width, code))

    def paint_blocks(self) -> None:
        """Save the cursor and restore it after, because curses tracks where it left it."""
        cells = "".join("\x1b[{};{}H\x1b[48;2;{};{};{}m{}".format(
            y + 1, x + 1, *bytes.fromhex(code[1:]), " " * width) for y, x, width, code in self.blocks)
        if cells:
            sys.stdout.write(f"\x1b7{cells}\x1b[0m\x1b8")
            sys.stdout.flush()

    def draw_panel(self, title: str, colours: list[tuple[str, str, str]], x: int, y: int, height: int) -> None:
        """A palette, one colour a line."""
        self.put(y, x, f"{title} palette", self.tint(2))
        if not colours:
            self.put(y + 2, x, "None in its README.")
        for row, (role, code, _) in enumerate(colours[:height - 1], 1):
            self.block(y + row, x, 4, code)
            self.put(y + row, x + 5, f"{role[:16]:<17}{code}")

    def draw_strip(self, rice: Rice | None, x: int, y: int, width: int) -> None:
        """A rice's whole palette as one bar, two lines tall."""
        if rice is None:
            return
        self.put(y, x + 2, rice.name, self.tint(2))
        colours = self.c.colours(rice)
        size = max(1, min(3, (width - 2) // max(1, len(colours))))
        for row in (y + 1, y + 2):
            for number, (_, code, _) in enumerate(colours):
                if x + 2 + (number + 1) * size <= x + width:
                    self.block(row, x + 2 + number * size, size, code)

    def rice_at(self, tab: str, side: str = "dark") -> object:
        """The value on the cursor's row of a list, once draw_list has clamped it."""
        rows = self.c.rows(tab, side)
        row = self.at.get((tab, side), 0)
        return rows[row][0] if row < len(rows) else None

    def lists(self) -> list[tuple[int, str]]:
        """The current tab's lists, as (column, side)."""
        return list(enumerate(self.SIDES)) if self.TABS[self.tab] == "Pair" else [(0, "dark")]

    def subtitle(self) -> str:
        tab = self.TABS[self.tab]
        name = self.c.rice.name if self.c.rice else "the rice"
        return {"Rice": "The rice to change to. Apply changes the theme, apps and open shells live.",
                "Wallpaper": f"Wallpapers for {name}.",
                "Pair": "The two rices flip moves between, one dark and one light.",
                "Cursors": f"Optional. Cursors for {name}. Asks for sudo, and shows after a reboot.",
                "Icons": f"Optional. Icon packs for {name}. Restart open apps to see a new one."}[tab]

    def draw_list(self, tab: str, side: str, x: int, width: int, y: int, height: int, focused: bool) -> None:
        rows = self.c.rows(tab, side)
        key = (tab, side)
        cur = self.at[key] = max(0, min(self.at.get(key, 0), len(rows) - 1))
        top = self.top.get(key, 0)
        top = cur if cur < top else cur - height + 1 if cur >= top + height else top
        self.top[key] = top = max(0, min(top, max(0, len(rows) - height)))
        picked = self.c.selected(tab, side)
        if tab == "Pair":
            self.put(y - 1, x + 2, side.capitalize(), self.tint(2))
        for row, (option, label, note) in list(enumerate(rows))[top:top + height]:
            text = f"{'>' if focused and row == cur else ' '} ({'x' if option == picked else ' '}) {label}"
            text = f"{text}  {note}" if note else text
            attr = self.bar() if focused and row == cur else 0
            self.put(y + row - top, x, text[:width].ljust(width), attr, ("row", tab, side, row))
        if not rows:
            self.put(y, x + 2, "Pick a rice first.")
        elif len(rows) == 1 and tab != "Rice":
            self.put(y + 1, x + 2, "This rice has none.")

    def draw(self) -> None:
        h, w = self.scr.getmaxyx()
        self.hits, self.blocks = [], []
        self.scr.erase()
        now = self.c.current.name if self.c.current else "none"
        self.put(0, 0, f" themebox  |  active: {now}".ljust(w - 1), self.bar())
        x = 1
        for number, tab in enumerate(self.TABS):
            label = f" {number + 1} {tab} "
            self.put(2, x, label, self.bar() if number == self.tab else self.tint(2), ("tab", number))
            x += len(label) + 1
        self.put(3, 1, self.subtitle())
        tab = self.TABS[self.tab]
        lists = self.lists()
        top = 6 if tab == "Pair" else 5
        height = max(1, h - top - 3)
        strips = tab == "Pair" and h >= 18  # below that the list needs the room more
        panel = tab in ("Rice", "Cursors", "Icons") and w >= PANEL_WIDTH + 40
        width = max(1, (w - 2) // len(lists) - 1) - (PANEL_WIDTH + 2 if panel else 0)
        for column, side in lists:
            self.draw_list(tab, side, 1 + column * (width + 1), width, top, height - 4 if strips else height,
                           column == self.side or len(lists) == 1)
            if strips:
                self.draw_strip(self.c.pair_shown(side, self.rice_at(tab, side)), 1 + column * (width + 1), h - 6, width)
        shown = self.c.panel(tab, self.rice_at(tab)) if panel else None
        if shown:
            self.draw_panel(*shown, w - PANEL_WIDTH - 1, top - 1, height + 1)
        changes = self.c.pending()
        self.put(h - 3, 1, self.status or ("Apply: " + ", ".join(changes) if changes else "Nothing to apply yet."),
                 self.tint(3) if self.status else 0)
        self.put(h - 2, 1, "[ Apply ]", self.bar() if changes else 0, ("apply",))
        self.put(h - 2, 11, "[ Quit ]", 0, ("quit",))
        self.put(h - 1, 0, " Tab: next tab   Up/Down: move   Space: pick   a: apply   q: quit".ljust(w - 1), self.bar())
        self.scr.refresh()
        self.paint_blocks()

    def focus(self) -> tuple[str, str]:
        tab = self.TABS[self.tab]
        return tab, self.SIDES[self.side] if tab == "Pair" else "dark"

    def go_tab(self, number: int) -> None:
        self.tab = number % len(self.TABS)
        self.side = 0

    def move(self, step: int) -> None:
        key = self.focus()
        self.at[key] = self.at.get(key, 0) + step

    def sideways(self, step: int) -> None:
        """Left and right change tabs, and on Pair cross the columns first."""
        side = self.side + step
        if self.TABS[self.tab] == "Pair" and side in (0, 1):
            self.side = side
        else:
            self.go_tab(self.tab + step)

    def pick(self, tab: str, side: str, row: int) -> None:
        rows = self.c.rows(tab, side)
        if row < len(rows):
            self.c.pick(tab, rows[row][0], side)

    def apply(self) -> bool:
        """True if the screen should close and the changes run."""
        self.status = self.c.problem() or ("" if self.c.pending() else "Nothing to apply yet.")
        return not self.status

    def click(self) -> str | None:
        with contextlib.suppress(curses.error):
            _, x, y, _, state = curses.getmouse()
            if state & curses.BUTTON4_PRESSED:
                self.move(-3)
            elif state & getattr(curses, "BUTTON5_PRESSED", 0):
                self.move(3)
            elif state & (curses.BUTTON1_PRESSED | curses.BUTTON1_CLICKED):
                self.status = ""
                return next((self.press(hit) for row, left, right, hit in self.hits
                             if row == y and left <= x < right), None)
        return None

    def press(self, hit: tuple) -> str | None:
        if hit[0] == "tab":
            self.go_tab(hit[1])
        elif hit[0] == "row":
            _, tab, side, row = hit
            self.side = self.SIDES.index(side) if tab == "Pair" else 0
            self.at[(tab, side)] = row
            self.pick(tab, side, row)
        elif hit[0] == "apply" and self.apply():
            return "apply"
        elif hit[0] == "quit":
            return "quit"
        return None

    def run(self) -> bool:
        """True if Apply was pressed."""
        keys = {curses.KEY_UP: lambda: self.move(-1), ord("k"): lambda: self.move(-1),
                curses.KEY_DOWN: lambda: self.move(1), ord("j"): lambda: self.move(1),
                curses.KEY_PPAGE: lambda: self.move(-10), curses.KEY_NPAGE: lambda: self.move(10),
                curses.KEY_HOME: lambda: self.move(-10**6), curses.KEY_END: lambda: self.move(10**6),
                curses.KEY_LEFT: lambda: self.sideways(-1), ord("h"): lambda: self.sideways(-1),
                curses.KEY_RIGHT: lambda: self.sideways(1), ord("l"): lambda: self.sideways(1),
                ord("\t"): lambda: self.go_tab(self.tab + 1), curses.KEY_BTAB: lambda: self.go_tab(self.tab - 1)}
        while True:
            self.draw()
            key = self.scr.getch()
            action = None
            if key != curses.KEY_MOUSE:  # a click's release must not wipe what the click said
                self.status = ""
            if key in (ord("q"), 27):
                return False
            if key == curses.KEY_MOUSE:
                action = self.click()
            elif key == ord("a"):
                action = "apply" if self.apply() else None
            elif key in (ord(" "), 10, 13, curses.KEY_ENTER):
                tab, side = self.focus()
                self.pick(tab, side, self.at.get((tab, side), 0))
            elif ord("1") <= key < ord("1") + len(self.TABS):
                self.go_tab(key - ord("1"))
            elif key in keys:
                keys[key]()
            if action:
                return action == "apply"


def open_screen(rices: list[Rice]) -> bool:
    """Run the tabs, then apply what they picked. False if a step failed."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise Error("the tabs need a terminal, see: themebox --help")
    os.environ.setdefault("ESCDELAY", "25")  # or Esc waits a full second to prove it is not an arrow key
    choices = Choices(rices)
    return not curses.wrapper(lambda scr: Screen(scr, choices).run()) or apply_choices(choices)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="themebox", description="Switch between COSMIC rices. "
                                 "With no command, opens tabs to pick from and apply.")
    sub = ap.add_subparsers(dest="command")
    sub.add_parser("list", help="every rice, * marks the active one")
    p = sub.add_parser("switch", help="make a rice active")
    p.add_argument("slug")
    p.add_argument("--keep-icons", action="store_true", help="leave the current icon theme alone")
    p.add_argument("--pick", action="store_true", help="choose the wallpaper from a list")
    p = sub.add_parser("wallpaper", help="list a rice's wallpapers, or save one for it")
    p.add_argument("slug")
    p.add_argument("name", nargs="?", help="the wallpaper to save, as listed")
    p = sub.add_parser("pair", help="match the rice to COSMIC's light/dark toggle")
    p.add_argument("--watch", action="store_true", help="keep following the toggle")
    p.add_argument("--keep-icons", action="store_true", help="leave the current icon theme alone")
    p.add_argument("--interval", type=float, default=2.0, help="seconds between checks with --watch")
    p = sub.add_parser("flip", help="move to the other half and change everything live")
    p.add_argument("--keep-icons", action="store_true", help="leave the current icon theme alone")
    p.add_argument("--pick", action="store_true", help="choose the wallpaper from a list")
    p = sub.add_parser("choose", help="flip between these two, one dark and one light")
    p.add_argument("rices", nargs="*", metavar="slug")
    p.add_argument("--reset", action="store_true", help="flip between each rice's own pair again")
    p = sub.add_parser("get", help="download a rice and its other half")
    p.add_argument("slug")
    p = sub.add_parser("capture", help="save the current theme and wallpaper as a new rice")
    p.add_argument("name")
    sub.add_parser("install-shell", help="let flip reload open zsh shells")
    args = ap.parse_args(argv)

    repos = Path(os.environ.get("THEMEBOX_REPOS") or Path(__file__).resolve().parent.parent).resolve()
    try:
        if args.command == "get":
            get(repos, args.slug)
            return 0
        if args.command == "capture":
            capture(repos, args.name)
            return 0
        rices = discover(repos)
        if not rices:
            raise Error(f"no rices in {repos} yet: themebox get <slug>, see {GALLERY}")
        if args.command is None:
            return 0 if open_screen(rices) else 1
        if args.command == "list":
            print_list(rices)
        elif args.command == "switch":
            target, previous = find(rices, args.slug), active(rices)
            chosen = ask_wallpaper(target) if args.pick else None
            ok = switch(target, rices, args.keep_icons)
            for message in apply_wallpaper(target, previous, chosen):
                print(f"  {message}")
            return 0 if ok else 1
        elif args.command == "wallpaper":
            rice = find(rices, args.slug)
            is_active = rice == active(rices)
            if args.name is None:
                print_wallpapers(rice, is_active)
                return 0
            path = find_wallpaper(rice, args.name)
            if path is None:
                raise Error(f"{rice.name} has no wallpaper {args.name}: themebox wallpaper {rice.slug} lists them")
            for message in save_wallpaper(rice, path, is_active):
                print(f"  {message}")
        elif args.command == "choose":
            if args.reset:
                reset_choice()
                print("flip uses each rice's own pair")
            elif len(args.rices) == 2:
                choose(rices, *args.rices)
                print(f"flip goes between {args.rices[0]} and {args.rices[1]}")
            else:
                raise Error("usage: themebox choose <dark> <light>, or --reset")
        elif args.command == "install-shell":
            print("Added to ~/.zshrc, new shells will reload" if install_shell() else "Already in ~/.zshrc")
        elif args.command == "flip":
            return 0 if flip(rices, args.keep_icons, args.pick) else 1
        elif args.watch:
            while True:
                follow(rices, args.keep_icons)
                time.sleep(args.interval)
        elif follow(rices, args.keep_icons) is None:
            print(f"{active(rices).name} already matches COSMIC's mode")
    except (Error, OSError, curses.error) as err:
        print(f"themebox: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
