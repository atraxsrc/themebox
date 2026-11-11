"""COSMIC after 1.11.0: icons and fonts live in the theme, and cosmic-bg keeps one wallpaper folder per mode.

The layout below is what the 2026-11-10/11 builds of cosmic-settings and cosmic-bg really write.
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import themebox as cr  # noqa: E402
from test_capture import STORED, CaptureBase  # noqa: E402
from test_flip import ALL, FlipBase  # noqa: E402

PARTS = [f"com.system76.CosmicTheme.{half}{builder}/v2" for half in ("Dark", "Light") for builder in ("", ".Builder")]


class Newer(FlipBase):
    def setUp(self):
        super().setUp()
        for part in PARTS:
            folder = self.conf / "cosmic" / part
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "icon_theme").write_text('"Cosmic"')
        self.walls = {}
        for half in ("Dark", "Light"):
            folder = self.conf / f"cosmic/com.system76.CosmicBackground.{half}/v1"
            folder.mkdir(parents=True)
            (folder / "same-on-all").write_text("true")
            self.walls[half] = folder
        (self.walls["Dark"] / "all").write_text(ALL)
        (self.walls["Light"] / "all").write_text(ALL.replace("/old/place/wall.png", "/old/light.png"))
        for slug in ("Noir", "Dossier"):
            (self.home / f".local/share/icons/Kanagawa-{slug}-Orange").mkdir(parents=True)

    def icons(self, part):
        return (self.conf / "cosmic" / part / "icon_theme").read_text()

    def wall(self, half):
        return cr.WALLPAPER.search((self.walls[half] / "all").read_text()).group(1)

    def import_resets_icons(self):
        """Make the cosmic-settings stub do what a real import of a .ron without icon_theme does."""
        resets = "".join(f'printf \'"Cosmic"\' > "$HOME/.config/cosmic/{part}/icon_theme"\n' for part in PARTS)
        self.stub("cosmic-settings", resets)


class Wallpaper(Newer):
    def test_flip_sets_the_wallpaper_of_the_new_mode(self):
        self.flip()
        self.assertEqual(self.wall("Light"), str(self.dossier / "backgrounds/dossier-anime.png"))
        self.assertEqual(self.wall("Dark"), "/old/place/wall.png")
        self.assertEqual((self.bg / "all").read_text(), ALL)  # the shared one is left for older COSMIC

    def test_the_wallpaper_left_in_the_other_mode_is_remembered(self):
        self.flip()
        self.assertEqual(cr.remembered(cr.find(self.rices(), "noir")), Path("/old/place/wall.png"))

    def test_round_trip_comes_back_to_both(self):
        mine = self.root / "my.png"
        mine.touch()
        (self.walls["Dark"] / "all").write_text(ALL.replace("/old/place/wall.png", str(mine)))
        self.flip()
        self.flip()
        self.assertEqual(self.wall("Dark"), str(mine))
        self.assertEqual(self.wall("Light"), str(self.dossier / "backgrounds/dossier-anime.png"))

    def test_a_mode_cosmic_bg_has_not_filled_is_seeded_from_the_shared_one(self):
        (self.walls["Light"] / "all").unlink()
        (self.walls["Light"] / "same-on-all").unlink()
        self.flip()
        self.assertEqual(self.wall("Light"), str(self.dossier / "backgrounds/dossier-anime.png"))
        self.assertEqual((self.walls["Light"] / "same-on-all").read_text(), "true")

    def test_separate_monitors_in_the_new_mode_are_a_manual_step(self):
        (self.walls["Light"] / "same-on-all").write_text("false")
        rices = self.rices()
        msgs = cr.apply_wallpaper(cr.find(rices, "dossier"), cr.find(rices, "noir"))
        self.assertTrue(msgs and msgs[0].startswith("Wallpaper:"))

    def test_the_wallpaper_in_use_is_the_current_modes(self):
        self.assertEqual(cr.desktop_wallpaper(), "/old/place/wall.png")
        cr.mode_file().write_text("false\n")
        self.assertEqual(cr.desktop_wallpaper(), "/old/light.png")


class Icons(Newer):
    def test_switch_puts_the_icons_in_the_theme_of_its_mode(self):
        self.switch("dossier", steps=False)
        for part in PARTS[2:]:
            self.assertEqual(self.icons(part), '"Kanagawa-Dossier-Orange"')
        for part in PARTS[:2]:
            self.assertEqual(self.icons(part), '"Cosmic"')

    def test_flip_puts_the_icons_back_after_the_import(self):
        self.import_resets_icons()
        ok, _ = self.flip()
        self.assertTrue(ok)
        self.assertEqual(self.icons(PARTS[2]), '"Kanagawa-Dossier-Orange"')
        self.assertEqual(self.icons(PARTS[3]), '"Kanagawa-Dossier-Orange"')

    def test_a_variant_of_the_rice_stays_through_the_import(self):
        (self.home / ".local/share/icons/Kanagawa-Noir-Sage").mkdir(parents=True)
        for part in PARTS[:2]:
            (self.conf / "cosmic" / part / "icon_theme").write_text('"Kanagawa-Noir-Sage"')
        self.import_resets_icons()
        with contextlib.redirect_stdout(io.StringIO()):
            cr.go_live(cr.find(self.rices(), "noir"), None, self.rices(), False, None)
        self.assertEqual(self.icons(PARTS[0]), '"Kanagawa-Noir-Sage"')

    def test_keep_icons_keeps_the_ones_showing(self):
        for part in PARTS[:2]:
            (self.conf / "cosmic" / part / "icon_theme").write_text('"Papirus"')
        self.import_resets_icons()
        with contextlib.redirect_stdout(io.StringIO()):
            cr.flip(self.rices(), keep_icons=True)
        self.assertEqual(self.icons(PARTS[2]), '"Papirus"')
        self.assertEqual((self.conf / "cosmic/com.system76.CosmicTk/v1/icon_theme").read_text(), '"Papirus"')

    def test_a_missing_default_falls_back_to_another_colour_of_the_pack(self):
        # COSMIC's own grey icons were showing, as after an import reset them
        icons = self.home / ".local/share/icons"
        (icons / "Kanagawa-Dossier-Orange").rmdir()
        (icons / "Kanagawa-Dossier-Olive").mkdir()
        (icons / "Kanagawa-Dossier-Dark").mkdir()
        self.switch("dossier", steps=False)
        self.assertEqual(self.icons(PARTS[2]), '"Kanagawa-Dossier-Dark"')
        self.assertEqual((self.conf / "cosmic/com.system76.CosmicTk/v1/icon_theme").read_text(),
                         '"Kanagawa-Dossier-Dark"')

    def test_no_colour_of_the_pack_installed_keeps_what_shows(self):
        (self.home / ".local/share/icons/Kanagawa-Dossier-Orange").rmdir()
        self.switch("dossier", steps=False)
        self.assertEqual(self.icons(PARTS[2]), '"Cosmic"')

    def test_icons_in_use_come_from_the_theme(self):
        (self.conf / "cosmic" / PARTS[0] / "icon_theme").write_text('"Kanagawa-Noir-Sage"')
        self.assertEqual(cr.icons_in_use(), "Kanagawa-Noir-Sage")

    def test_older_cosmic_gets_no_theme_icon_files(self):
        for part in PARTS:
            (self.conf / "cosmic" / part / "icon_theme").unlink()
        self.switch("dossier", steps=False)
        self.assertFalse(any((self.conf / "cosmic" / part / "icon_theme").exists() for part in PARTS))
        self.assertIn("Kanagawa-Dossier-Orange", (self.conf / "cosmic/com.system76.CosmicTk/v1/icon_theme").read_text())


class Capture(CaptureBase):
    def test_fonts_and_icons_come_from_the_theme_not_stale_cosmictk(self):
        tk = self.conf / "cosmic/com.system76.CosmicTk/v1"
        tk.mkdir(parents=True, exist_ok=True)
        (tk / "icon_theme").write_text('"Stale"')
        (tk / "show_minimize").write_text("false")
        font = '(\n    family: "Maple",\n    weight: Light,\n)'
        self.store("Dark", {**STORED, "icon_theme": '"Cosmic-Mine"', "font": font})
        with contextlib.redirect_stdout(io.StringIO()):
            cr.capture(self.repos, "Mine")
        saved = self.repos / "cosmic-mine-theme/cosmic/config/com.system76.CosmicTk/v1"
        self.assertEqual((saved / "icon_theme").read_text(), '"Cosmic-Mine"')
        self.assertEqual((saved / "interface_font").read_text(), font)
        self.assertEqual((saved / "show_minimize").read_text(), "false")
        self.assertIn('icon_theme: "Cosmic-Mine"', self.ron())

    def test_the_wallpaper_comes_from_the_current_modes_folder(self):
        dark = self.conf / "cosmic/com.system76.CosmicBackground.Dark/v1"
        dark.mkdir(parents=True)
        mine = self.root / "pics/dark one.png"
        mine.write_bytes(b"dark")
        (dark / "all").write_text(ALL.replace("/old/place/wall.png", str(mine)))
        (dark / "same-on-all").write_text("true")
        with contextlib.redirect_stdout(io.StringIO()):
            cr.capture(self.repos, "Mine")
        self.assertEqual((self.repos / "cosmic-mine-theme/backgrounds/mine-dark one.png").read_bytes(), b"dark")


if __name__ == "__main__":
    unittest.main()
