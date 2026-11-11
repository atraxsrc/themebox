"""The CLI must leave a HOME exactly as the repos' own scripts/switch.sh does.

Runs both against the real sibling repos in a throwaway HOME. Skipped once
switch.sh is gone from the repos, or when they are not checked out here.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOS = Path(os.environ.get("THEMEBOX_REPOS") or ROOT.parent)
sys.path.insert(0, str(ROOT))
import themebox as cr  # noqa: E402

PREVIOUS = "noir"  # in every old switch.sh list, so both sides park its nvim spec
PREVIOUS_ALT = "darkgold"


VOLATILE = {".cache/bat/metadata.yaml"}  # bat stamps the build time in it
CLI_ONLY = {f".config/cosmic/com.system76.CosmicTerm/v1/color_schemes_{mode}" for mode in ("dark", "light")}


def seed(home: Path, rices: list, target, prev) -> None:
    conf = home / ".config"
    (home / ".mozilla/firefox/abc.default-release").mkdir(parents=True)
    (conf / "btop").mkdir(parents=True)
    (conf / "btop/btop.conf").write_text('color_theme = "old"\nupdate_ms = 2000\n')
    plugins = conf / "nvim/lua/plugins"
    plugins.mkdir(parents=True)
    (plugins / f"{prev.slug}.lua").write_text("-- previous\n")
    (plugins / "keymaps.lua").write_text("-- mine\n")
    term = conf / "cosmic/com.system76.CosmicTerm/v1"
    term.mkdir(parents=True)
    (term / "syntax_theme_dark").write_text('"Someone Else"')
    (term / "font_size").write_text("11")
    (conf / "btop/btop.conf").chmod(0o600)
    (home / ".zshrc").touch(mode=0o600)
    (home / ".zshrc").write_text(
        "export KEEP=1\n"
        f"source {prev.repo}/zsh/{prev.slug}.zsh\n"
        f"# source {target.repo}/zsh/{target.slug}.zsh\n")


def tree(home: Path) -> dict:
    out = {}
    for p in sorted(home.rglob("*")):
        rel = str(p.relative_to(home))
        # fc-cache stamps its cache files, so two runs never match byte for byte
        if rel in VOLATILE | CLI_ONLY or rel.startswith(".cache/fontconfig/"):
            continue
        if p.is_symlink():
            out[rel] = ("link", os.readlink(p))
        elif p.is_file():
            out[rel] = ("file", p.stat().st_mode, p.read_bytes())
    return out


def run(cmd: list, home: Path) -> None:
    env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
           "THEMEBOX_REPOS": str(REPOS), "DBUS_SESSION_BUS_ADDRESS": "disabled:"}
    done = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    assert done.returncode == 0, f"{cmd}\n{done.stdout[-2000:]}"


@unittest.skipUnless(list(REPOS.glob("cosmic-*-theme/scripts/switch.sh")), "no rice repos with switch.sh")
class Parity(unittest.TestCase):
    def test_every_rice_matches_switch_sh(self):
        rices = cr.discover(REPOS)
        self.assertEqual(len(rices), 28)
        for target in rices:
            with self.subTest(target.slug), tempfile.TemporaryDirectory() as t:
                prev = cr.find(rices, PREVIOUS_ALT if target.slug == PREVIOUS else PREVIOUS)
                home = Path(t) / "home"
                home.mkdir()
                seed(home, rices, target, prev)
                run([str(target.repo / "scripts/switch.sh")], home)
                old = tree(home)
                shutil.rmtree(home)
                home.mkdir()
                seed(home, rices, target, prev)
                run([str(ROOT / "themebox.py"), "switch", target.slug], home)
                new = tree(home)
                self.assertEqual(sorted(old), sorted(new))
                self.assertEqual([k for k in old if old[k] != new[k]], [])


if __name__ == "__main__":
    unittest.main()
