#!/usr/bin/env python3
"""Switch between COSMIC rices: the cosmic-*-theme repos next to this one.

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
import io
import os
import re
import shutil
import signal
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
ZSH_SOURCE = r"^\s*#?\s*(?:source|\.)\s.*"
ZSH_ANY = re.compile(ZSH_SOURCE + r"(?:cosmic-[a-z0-9]+-theme/zsh/[a-z0-9]+\.zsh|ricing/zsh/colors\.zsh)")


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
            if keep_icons:
                print(f"  cosmic: icons stay {have or 'default'} (--keep-icons)")
                continue
            if have.startswith(want.rsplit("-", 1)[0] + "-"):
                print(f"  cosmic: icons stay {have}")
                continue
            if not icons_installed(want):
                print(f"  cosmic: icons stay {have or 'default'}, {want} is not installed (./icons/install.sh)")
                continue
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


def desktop_wallpaper() -> str | None:
    entry = config_dir() / "cosmic/com.system76.CosmicBackground/v1/all"
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
    """Change only the path in cosmic-bg's entry for all monitors.

    Uses chosen if given, else what this rice last had, else its default.
    Staying on the same rice keeps the wallpaper unless one was chosen.
    """
    folder = config_dir() / "cosmic/com.system76.CosmicBackground/v1"
    manual = f"Wallpaper: Settings → Wallpaper → a file from {rice.repo}/backgrounds"
    entry = folder / "all"
    if value(folder / "same-on-all") == "false" or not entry.is_file():
        return [manual]
    text = entry.read_text()
    current = desktop_wallpaper()
    if current is None:
        return [manual]
    if chosen is None and previous == rice:
        return []
    if previous:
        remember(previous, current)
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
    marked = desktop_wallpaper() if is_active else remembered(rice)
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
    root = config_dir() / f"cosmic/com.system76.CosmicTheme.{mode.capitalize()}.Builder"
    folders = [p for p in root.glob("v*") if p.is_dir() and p.name[1:].isdigit()]
    newest = max(folders, key=lambda p: int(p.name[1:]), default=None)
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


def copy_wallpaper(repo: Path, slug: str) -> str | None:
    """Copy the desktop's wallpaper into repo/backgrounds. Its file name, None if there is no one file."""
    folder = config_dir() / "cosmic/com.system76.CosmicBackground/v1"
    current = desktop_wallpaper()
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
    mode = "light" if value(mode_file()) == "false" else "dark"
    ron = f"{name.replace(' ', '')}.ron"
    theme = theme_ron(mode, name)
    repos.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=repos, prefix=".capture-") as tmp:
        build = Path(tmp) / "rice"
        (build / "cosmic").mkdir(parents=True)
        (build / "cosmic" / ron).write_text(theme)
        for setting in TK_LOOK:
            live = config_dir() / "cosmic/com.system76.CosmicTk/v1" / setting
            if live.is_file():
                saved = build / "cosmic/config/com.system76.CosmicTk/v1" / setting
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(live, saved)
        wallpaper = copy_wallpaper(build, slug)
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
    # switch comes first so a running pair --watch already sees the new half
    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        switched = switch(target, rices, keep_icons, steps=False)
    if not switched:
        print(log.getvalue())
    messages = [] if switched else [f"{FAILED} some tools, run themebox flip in a terminal to see which"]
    messages += apply_theme(target) + apply_wallpaper(target, current, chosen) + reload_nvim(target)
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="themebox", description="Switch between COSMIC rices.")
    sub = ap.add_subparsers(dest="command", required=True)
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
    except (Error, OSError) as err:
        print(f"themebox: {err}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
