"""cosmic-rice flip, with stub desktop commands first on PATH."""
import contextlib
import io
import os
import stat
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cosmic_rice as cr  # noqa: E402
from test_cli import Base  # noqa: E402

ALL = '''(
    output: "all",
    source: Path("/old/place/wall.png"),
    filter_by_theme: true,
    rotation_frequency: 300,
    filter_method: Lanczos,
    scaling_mode: Zoom,
    sampling_method: Alphanumeric,
)
'''


class FlipBase(Base):
    def setUp(self):
        super().setUp()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "stub.log"
        for name in ("cosmic-settings", "notify-send"):
            self.stub(name, f'echo "{name} $* | $(readlink "$HOME/update_system.sh") | '
                            f'$(cat "$HOME/.config/cosmic/com.system76.CosmicTheme.Mode/v1/is_dark")" >> "{self.log}"\n')
        self.run_dir = self.root / "run"
        self.run_dir.mkdir()
        self.stub("nvim", f'echo "nvim $*" >> "{self.log}"\n')
        patch = unittest.mock.patch.dict(os.environ, {"PATH": f"{self.bin}:{os.environ['PATH']}",
                                                      "XDG_RUNTIME_DIR": str(self.run_dir)})
        patch.start()
        self.addCleanup(patch.stop)
        for repo, slug, name in ((self.noir, "noir", "Noir"), (self.dossier, "dossier", "Dossier")):
            (repo / "backgrounds").mkdir()
            for subject in ("anime", "city"):
                (repo / f"backgrounds/{slug}-{subject}.png").touch()
            (repo / f"cosmic/{name}.ron").write_text("()")
            (repo / "cosmic-term").mkdir()
            (repo / f"cosmic-term/{name}-term.ron").write_text(f'(\n    name: "{name}",\n)\n')
        self.bg = self.conf / "cosmic/com.system76.CosmicBackground/v1"
        self.bg.mkdir(parents=True)
        (self.bg / "all").write_text(ALL)
        (self.bg / "same-on-all").write_text("true")
        self.switch("noir", steps=False)

    def stub(self, name, body, code=0):
        f = self.bin / name
        f.write_text(f"#!/bin/sh\n{body}exit {code}\n")
        f.chmod(f.stat().st_mode | stat.S_IXUSR)

    def flip(self):
        rices = self.rices()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = cr.flip(rices)
        return ok, buf.getvalue()

    def stub_log(self):
        return self.log.read_text() if self.log.exists() else ""


class Theme(FlipBase):
    def test_flip_moves_to_the_pair_and_imports_its_theme(self):
        self.flip()
        self.assertEqual(cr.active(self.rices()).slug, "dossier")
        self.assertIn(f"appearance import {self.dossier}/cosmic/Dossier.ron", self.stub_log())

    def test_link_and_mode_are_set_before_the_import(self):
        self.flip()
        line = next(x for x in self.stub_log().splitlines() if x.startswith("cosmic-settings"))
        self.assertIn(f"{self.dossier}/scripts/update_system.sh | false", line)

    def test_failed_import_still_flips_and_returns_false(self):
        self.stub("cosmic-settings", "", code=1)
        ok, out = self.flip()
        self.assertFalse(ok)
        self.assertEqual(cr.active(self.rices()).slug, "dossier")
        self.assertIn("theme", out)

    def test_missing_cosmic_settings_is_reported_not_raised(self):
        (self.bin / "cosmic-settings").unlink()
        with unittest.mock.patch.dict(os.environ, {"PATH": str(self.bin)}):
            ok = cr.apply_theme(cr.find(self.rices(), "dossier"))
        self.assertTrue(ok[0].startswith("failed:"))

    def test_no_active_rice_is_an_error(self):
        (self.home / "update_system.sh").unlink()
        with self.assertRaisesRegex(cr.Error, "active"):
            self.flip()

    def test_no_pair_is_an_error(self):
        for repo in (self.noir, self.dossier):
            (repo / "README.md").write_text("# x\n\n## Palette\n")
        with self.assertRaisesRegex(cr.Error, "pair"):
            self.flip()


class Wallpaper(FlipBase):
    def pick(self, current):
        rices = self.rices()
        return cr.pick_wallpaper(cr.find(rices, "dossier"), cr.find(rices, "noir"), current)

    def test_same_subject_is_kept(self):
        self.assertEqual(self.pick(f"{self.noir}/backgrounds/noir-city.png").name, "dossier-city.png")

    def test_missing_subject_falls_back_to_anime_then_first(self):
        self.assertEqual(self.pick(f"{self.noir}/backgrounds/noir-rain.png").name, "dossier-anime.png")
        (self.dossier / "backgrounds/dossier-anime.png").unlink()
        (self.dossier / "backgrounds/dossier-bay.png").touch()
        self.assertEqual(self.pick(f"{self.noir}/backgrounds/noir-rain.png").name, "dossier-bay.png")

    def test_foreign_wallpaper_uses_anime(self):
        self.assertEqual(self.pick("/home/me/Pictures/city.png").name, "dossier-anime.png")

    def test_no_backgrounds_leaves_wallpaper_alone(self):
        for f in (self.dossier / "backgrounds").iterdir():
            f.unlink()
        self.assertIsNone(self.pick("/x.png"))
        self.flip()
        self.assertEqual((self.bg / "all").read_text(), ALL)

    def test_rewrite_keeps_other_fields_and_odd_paths(self):
        (self.bg / "all").write_text(ALL.replace("/old/place/wall.png", f"{self.noir}/backgrounds/noir-city.png"))
        odd = self.root / "my walls #2\\x"
        odd.mkdir()
        rice = cr.find(self.rices(), "dossier")
        rice.repo = odd
        (odd / "backgrounds").mkdir()
        (odd / "backgrounds/dossier-city.png").touch()
        cr.apply_wallpaper(rice, cr.find(self.rices(), "noir"))
        want = str(odd / "backgrounds/dossier-city.png").replace("\\", "\\\\")
        expected = ALL.replace("/old/place/wall.png", want)
        self.assertEqual((self.bg / "all").read_text(), expected)
        self.assertTrue((self.bg / "all.bak").is_file())

    def test_an_escaped_path_can_be_read_back(self):
        (self.bg / "all").write_text(ALL.replace("/old/place/wall.png", "/a\\\"b.png"))
        rices = self.rices()
        self.assertEqual(cr.apply_wallpaper(cr.find(rices, "dossier"), cr.find(rices, "noir")), [])
        self.assertIn("dossier-anime.png", (self.bg / "all").read_text())

    def test_separate_monitors_become_a_manual_step(self):
        (self.bg / "same-on-all").write_text("false")
        rices = self.rices()
        msgs = cr.apply_wallpaper(cr.find(rices, "dossier"), cr.find(rices, "noir"))
        self.assertEqual((self.bg / "all").read_text(), ALL)
        self.assertIn("Wallpaper", msgs[0])


class Report(FlipBase):
    def test_report_lists_firefox_and_claude_and_goes_to_notify_send(self):
        _, out = self.flip()
        self.assertIn("Firefox", out)
        self.assertIn("Claude Desktop", out)
        line = next(x for x in self.stub_log().splitlines() if x.startswith("notify-send"))
        self.assertIn("Firefox", line)
        self.assertIn("Dossier", line)

    def test_missing_notify_send_is_not_a_failure(self):
        (self.bin / "notify-send").unlink()
        self.assertTrue(self.flip()[0])

    def test_scheme_step_only_when_name_is_missing(self):
        rice = cr.find(self.rices(), "dossier")
        self.assertTrue(any("COSMIC Terminal" in m for m in cr.leftovers(rice)))
        d = self.conf / "cosmic/com.system76.CosmicTerm/v1"
        (d / "color_schemes_light").write_text('{1: (name: "Dossier",),}')
        self.assertFalse(any("COSMIC Terminal" in m for m in cr.leftovers(rice)))

    def test_flip_command_exit_codes(self):
        env = {"COSMIC_RICE_REPOS": str(self.repos)}
        with unittest.mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cr.main(["flip"]), 0)
            self.assertEqual(cr.active(self.rices()).slug, "dossier")
            self.stub("cosmic-settings", "", code=1)
            self.assertEqual(cr.main(["flip"]), 1)


class Nvim(FlipBase):
    def setUp(self):
        super().setUp()
        (self.run_dir / "nvim.me/abc").mkdir(parents=True)
        (self.run_dir / "nvim.me/abc/nvim.1.0").touch()
        (self.run_dir / "nvim.2.0").touch()
        (self.dossier / "nvim/colors").mkdir()
        (self.dossier / "nvim/colors/dossier.lua").touch()

    def test_each_socket_gets_the_colorscheme(self):
        self.assertEqual(cr.reload_nvim(cr.find(self.rices(), "dossier")), [])
        lines = [x for x in self.stub_log().splitlines() if x.startswith("nvim")]
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIn("--server", line)
            self.assertIn("execute('colorscheme dossier')", line)

    def test_dead_socket_is_skipped(self):
        self.stub("nvim", "", code=1)
        self.assertEqual(cr.reload_nvim(cr.find(self.rices(), "dossier")), [])

    def test_no_runtime_dir_or_colors_is_quiet(self):
        with unittest.mock.patch.dict(os.environ):
            del os.environ["XDG_RUNTIME_DIR"]
            self.assertEqual(cr.nvim_sockets(), [])
        self.assertEqual(cr.reload_nvim(cr.find(self.rices(), "noir")), [])
        self.assertEqual(self.stub_log().count("nvim --server"), 0)

    def test_flip_reloads_nvim(self):
        self.flip()
        self.assertIn("colorscheme dossier", self.stub_log())


if __name__ == "__main__":
    unittest.main()
