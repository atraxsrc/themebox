"""themebox capture: the live COSMIC theme and wallpaper into a new rice folder.

The stored values below are what cosmic-settings really writes after an import.
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import themebox as cr  # noqa: E402
from test_flip import ALL, FlipBase  # noqa: E402

STORED = {
    "palette": 'Dark((\n    name: "Old Name",\n    bright_red: "#F25623FF",\n))',
    "spacing": "(\n    space_none: 0,\n)",
    "corner_radii": "(\n    radius_0: (0.0, 0.0, 0.0, 0.0),\n)",
    "gaps": "(0, 7)",
    "active_hint": "1",
    "accent": 'Some("#F25623FF")',
    "window_hint": "None",
    "frosted": "Low",
}


class CaptureBase(FlipBase):
    def setUp(self):
        super().setUp()
        self.mode("true")
        self.store("Dark", STORED)
        self.wall = self.root / "pics/my wall.png"
        self.wall.parent.mkdir()
        self.wall.write_bytes(b"picture")
        (self.bg / "all").write_text(ALL.replace("/old/place/wall.png", str(self.wall)))

    def store(self, half, fields, version="v2"):
        folder = self.conf / f"cosmic/com.system76.CosmicTheme.{half}.Builder/{version}"
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in fields.items():
            (folder / name).write_text(text)
        return folder

    def mode(self, is_dark):
        cr.mode_file().parent.mkdir(parents=True, exist_ok=True)
        cr.mode_file().write_text(is_dark)

    def capture(self, name="Mine"):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cr.capture(self.repos, name)
        return out.getvalue()

    def ron(self, name="Mine.ron", slug="mine"):
        return (self.repos / f"cosmic-{slug}-theme/cosmic" / name).read_text()


class Theme(CaptureBase):
    def test_makes_a_rice_themebox_can_read(self):
        self.capture()
        r = cr.find(self.rices(), "mine")
        self.assertEqual((r.name, r.mode, r.ron), ("Mine", "dark", "Mine.ron"))

    def test_the_ron_holds_every_stored_field(self):
        self.capture()
        self.assertIn('accent: Some("#F25623FF"),', self.ron())
        self.assertIn("gaps: (0, 7),", self.ron())

    def test_the_ron_is_one_struct(self):
        self.capture()
        self.assertTrue(self.ron().startswith("(\n    "))
        self.assertTrue(self.ron().endswith("\n)\n"))

    def test_the_palette_takes_the_new_name(self):
        self.capture()
        self.assertIn('palette: Dark((\n        name: "Mine",', self.ron())
        self.assertNotIn("Old Name", self.ron())

    def test_light_mode_reads_the_light_theme(self):
        self.mode("false")
        self.store("Light", {**STORED, "palette": 'Light((\n    name: "Old",\n))'})
        self.capture()
        self.assertEqual(cr.find(self.rices(), "mine").mode, "light")
        self.assertIn("Light((", self.ron())

    def test_no_mode_file_means_dark(self):
        cr.mode_file().unlink()
        self.capture()
        self.assertEqual(cr.find(self.rices(), "mine").mode, "dark")

    def test_reads_the_newest_version_folder(self):
        self.store("Dark", {**STORED, "gaps": "(1, 1)"}, version="v1")
        self.store("Dark", {**STORED, "gaps": "(3, 3)"}, version="v10")
        self.capture()
        self.assertIn("gaps: (3, 3),", self.ron())

    def test_backup_files_stay_out_of_the_ron(self):
        (self.store("Dark", {}) / "accent.bak").write_text("junk")
        self.capture()
        self.assertNotIn("junk", self.ron())

    def test_colours_cosmic_never_stored_are_none(self):
        self.capture()
        self.assertIn("text_tint: None,", self.ron())

    def test_a_theme_with_no_palette_is_refused(self):
        (self.store("Dark", {}) / "palette").unlink()
        with self.assertRaisesRegex(cr.Error, "palette"):
            self.capture()

    def test_a_refused_capture_leaves_no_folder(self):
        (self.store("Dark", {}) / "palette").unlink()
        with self.assertRaises(cr.Error):
            self.capture()
        self.assertEqual(list(self.repos.glob("*mine*")), [])

    def test_a_name_with_a_space(self):
        self.capture("Mine Day")
        r = cr.find(self.rices(), "mineday")
        self.assertEqual((r.name, r.ron), ("Mine Day", "MineDay.ron"))
        self.assertIn('name: "Mine Day"', self.ron("MineDay.ron", "mineday"))


class Names(CaptureBase):
    def test_a_name_that_cannot_be_a_folder_is_refused(self):
        for name in ("", "   ", "../evil", 'Mi"ne', "mine\n"):
            with self.subTest(name=name), self.assertRaisesRegex(cr.Error, "name"):
                self.capture(name)

    def test_an_existing_rice_is_refused_and_kept(self):
        before = (self.noir / "README.md").read_text()
        with self.assertRaisesRegex(cr.Error, "already"):
            self.capture("Noir")
        self.assertEqual((self.noir / "README.md").read_text(), before)
        self.assertFalse((self.noir / "rice.toml").exists())


class Wallpaper(CaptureBase):
    def test_copies_the_wallpaper_under_the_rice_name(self):
        self.capture()
        copied = self.repos / "cosmic-mine-theme/backgrounds/mine-my wall.png"
        self.assertEqual(copied.read_bytes(), b"picture")

    def test_switching_to_the_rice_uses_the_copy(self):
        self.capture()
        self.switch("mine", steps=False)
        wall = cr.apply_wallpaper(cr.find(self.rices(), "mine"), cr.find(self.rices(), "noir"))
        self.assertEqual(wall, [])
        self.assertIn("cosmic-mine-theme/backgrounds/mine-my wall.png", (self.bg / "all").read_text())

    def test_a_missing_file_still_captures_the_theme(self):
        self.wall.unlink()
        self.assertIn("Wallpaper", self.capture())
        self.assertIn("Mine", [r.name for r in self.rices()])
        self.assertFalse((self.repos / "cosmic-mine-theme/backgrounds").exists())

    def test_a_folder_of_wallpapers_is_not_copied(self):
        (self.bg / "all").write_text(ALL.replace("/old/place/wall.png", str(self.wall.parent)))
        self.assertIn("Wallpaper", self.capture())
        self.assertFalse((self.repos / "cosmic-mine-theme/backgrounds").exists())

    def test_a_plain_colour_desktop_is_reported(self):
        (self.bg / "all").write_text('(\n    output: "all",\n    source: Color(Single((0.0, 0.0, 0.0))),\n)\n')
        self.assertIn("Wallpaper", self.capture())

    def test_different_wallpapers_per_monitor_are_reported(self):
        (self.bg / "same-on-all").write_text("false")
        self.assertIn("Wallpaper", self.capture())
        self.assertFalse((self.repos / "cosmic-mine-theme/backgrounds").exists())


class Looks(CaptureBase):
    def tk(self):
        folder = self.conf / "cosmic/com.system76.CosmicTk/v1"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def test_keeps_the_icons_and_fonts(self):
        (self.tk() / "icon_theme").write_text('"Cosmic-Mine"')
        (self.tk() / "interface_font").write_text("(family: \"Maple\")")
        self.capture()
        saved = self.repos / "cosmic-mine-theme/cosmic/config/com.system76.CosmicTk/v1"
        self.assertEqual((saved / "icon_theme").read_text(), '"Cosmic-Mine"')
        self.assertEqual((saved / "interface_font").read_text(), '(family: "Maple")')

    def test_a_backup_of_a_look_setting_is_left_behind(self):
        (self.tk() / "icon_theme.bak").write_text("old")
        self.capture()
        self.assertFalse((self.repos / "cosmic-mine-theme/cosmic/config/com.system76.CosmicTk/v1/icon_theme.bak").exists())


class Commandline(CaptureBase):
    def test_works_with_no_rices_yet(self):
        empty = self.root / "empty"
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cr.capture(empty, "Mine")
        self.assertEqual(cr.discover(empty)[0].slug, "mine")

    def test_says_how_to_use_it(self):
        self.assertIn("themebox switch mine", self.capture())

    def test_leaves_no_temporary_folder(self):
        self.capture()
        self.assertEqual([p.name for p in self.repos.glob(".*")], [])

    def test_does_not_change_the_desktop(self):
        before = (self.bg / "all").read_text()
        self.capture()
        self.assertEqual((self.bg / "all").read_text(), before)
        self.assertEqual(cr.active(self.rices()).slug, "noir")


if __name__ == "__main__":
    unittest.main()
