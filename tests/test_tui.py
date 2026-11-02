"""themebox's tabs: the choices behind them, and the real screen on a pseudo-terminal."""
import contextlib
import fcntl
import io
import os
import pty
import select
import shutil
import stat
import struct
import subprocess
import sys
import termios
import time
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import themebox as cr  # noqa: E402
from test_flip import FlipBase  # noqa: E402

THEMEBOX = Path(__file__).resolve().parent.parent / "themebox.py"
ROWS, COLS = 24, 80


def swatch(code):
    return f"![#{code}](https://placehold.co/12x12/{code}/{code}.png)"


NOIR_README = f"""# COSMIC · Noir

The dark half; the light half is [x](https://github.com/atraxsrc/cosmic-dossier-theme).

## Palette

Some words about {swatch("123456")} the colours.

| Role | Color | Hex |
|------|-------|-----|
| Background | {swatch("171717")} Charcoal | {swatch("171717")} `#171717` |
| Text | {swatch("ccd0cf")} Fog | {swatch("CCD0CF")} `#CCD0CF` |
| Error | {swatch("f25623")} Orange | {swatch("F25623")} `#F25623` |
| Accent | {swatch("F25623")} Orange | {swatch("F25623")} `#F25623` |

Prose after the table.

| Role | Noir | Dossier |
|------|------|---------|
| Background | {swatch("171717")} `#171717` | {swatch("D0D0C8")} `#D0D0C8` |

## Setup

| Thing | {swatch("ABCDEF")} Not a colour | x |
"""
DOSSIER_README = NOIR_README.replace("Noir", "Dossier").replace("cosmic-dossier-theme", "cosmic-noir-theme") \
    .replace("171717", "D0D0C8").replace("The dark half; the light", "The light half; the dark")


def write_cursor(theme, colours):
    """A cursor file: one small image first, then a larger one with the given opaque pixels."""
    (theme / "cursors").mkdir(parents=True, exist_ok=True)
    images = [(24, [(1, 2, 3)]), (48, colours + [(255, 255, 255), (0, 0, 0)])]
    start = 16 + 12 * len(images)
    toc, body = b"", b""
    for size, pixels in images:
        toc += struct.pack("<III", 0xfffd0002, size, start + len(body))
        body += struct.pack("<IIIIIIIII", 36, 0xfffd0002, size, 1, len(pixels), 1, 0, 0, 0)
        body += b"".join(bytes((b, g, r, 255)) for r, g, b in pixels)
    (theme / "cursors/left_ptr").write_bytes(b"Xcur" + struct.pack("<III", 16, 0x10000, len(images)) + toc + body)


def click(column, row):
    """A left press and release, as a terminal sends them. Both numbers start at 0."""
    place = f"{column + 1};{row + 1}"
    return f"\x1b[<0;{place}M\x1b[<0;{place}m"


class TuiBase(FlipBase):
    def setUp(self):
        super().setUp()
        self.calls = self.root / "installers.log"
        for repo, name in ((self.noir, "Noir"), (self.dossier, "Dossier")):
            for tool in ("cursors", "icons"):
                script = repo / tool / "install.sh"
                script.parent.mkdir()
                script.write_text(f'#!/usr/bin/env bash\nVARIANTS=(Orange Sage)\necho "{tool} {name} $*" >> "{self.calls}"\n')
                script.chmod(script.stat().st_mode | stat.S_IXUSR)
            (repo / f"cursors/Oxygen-{name}-Sage").mkdir()
            (repo / "cosmic/config/com.system76.CosmicTk/v1/icon_theme").write_text(f'"Fake-{name}-Orange"')
        (self.noir / "README.md").write_text(NOIR_README)
        (self.dossier / "README.md").write_text(DOSSIER_README)

    def choices(self):
        return cr.Choices(self.rices())

    def apply(self, choices):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            done = cr.apply_choices(choices)
        return done, out.getvalue()

    def active(self):
        return os.readlink(self.home / "update_system.sh")

    def wallpaper(self):
        return cr.desktop_wallpaper()


class Rows(TuiBase):
    def test_starts_on_the_active_rice_with_nothing_to_do(self):
        c = self.choices()
        self.assertEqual(c.rice.slug, "noir")
        self.assertEqual(c.pending(), [])

    def test_rice_rows_are_sorted_and_mark_the_active_one(self):
        rows = self.choices().rows("Rice")
        self.assertEqual([r[0].slug for r in rows], ["dossier", "k3", "k3day", "noir"])
        self.assertEqual([r[0].slug for r in rows if r[2] == "active"], ["noir"])

    def test_wallpaper_rows_belong_to_the_picked_rice(self):
        c = self.choices()
        c.pick("Rice", cr.find(c.rices, "dossier"))
        self.assertEqual([r[1] for r in c.rows("Wallpaper")], ["Saved or default", "anime", "city"])

    def test_wallpaper_in_use_is_marked(self):
        c = self.choices()
        self.assertEqual([r[1] for r in c.rows("Wallpaper") if r[2] == "in use"], [])
        cr.save_wallpaper(c.rice, cr.find_wallpaper(c.rice, "city"), True)
        self.assertEqual([r[1] for r in c.rows("Wallpaper") if r[2] == "in use"], ["city"])

    def test_cursor_and_icon_rows_start_with_keep_current(self):
        c = self.choices()
        for tab in ("Cursors", "Icons"):
            self.assertEqual([r[1] for r in c.rows(tab)], ["Keep current", "Orange", "Sage"])
            self.assertIsNone(c.rows(tab)[0][0])

    def test_icon_rows_say_what_is_here(self):
        c = self.choices()
        self.assertEqual({r[1]: r[2] for r in c.rows("Icons")[1:]}, {"Orange": "downloads", "Sage": "downloads"})
        (self.home / ".local/share/icons/Fake-Noir-Sage").mkdir(parents=True)
        self.assertEqual(c.rows("Icons")[2][2], "installed")

    def test_browsing_never_runs_a_rice_script(self):
        c = self.choices()
        for tab in ("Cursors", "Icons"):
            c.rows(tab)
            c.panel(tab, "Sage")
        self.assertFalse(self.calls.exists())

    def test_a_variant_list_with_an_odd_name_is_ignored(self):
        (self.noir / "cursors/install.sh").write_text('#!/bin/sh\nVARIANTS=(Sage "$(touch x)" ../up)\n')
        self.assertEqual(cr.variants(cr.find(self.rices(), "noir"), "cursors"), [])

    def test_a_rice_without_cursors_only_offers_keep(self):
        c = self.choices()
        c.pick("Rice", cr.find(c.rices, "k3"))
        self.assertEqual(len(c.rows("Cursors")), 1)

    def test_pair_columns_only_hold_their_own_mode(self):
        c = self.choices()
        self.assertEqual([r[0] for r in c.rows("Pair", "dark")], [None, "k3", "noir"])
        self.assertEqual([r[0] for r in c.rows("Pair", "light")], [None, "dossier", "k3day"])


class Palette(TuiBase):
    def test_reads_only_the_first_table(self):
        self.assertEqual(cr.palette(cr.find(self.rices(), "noir")),
                         [("Background", "#171717", "Charcoal"), ("Text", "#CCD0CF", "Fog"), ("Error", "#F25623", "Orange")])

    def test_a_rice_without_a_table_has_no_palette(self):
        self.assertEqual(cr.palette(cr.find(self.rices(), "k3")), [])
        (self.k3 / "README.md").unlink()
        self.assertEqual(cr.palette(cr.find(self.rices(), "k3")), [])

    def test_cursor_colours_come_from_the_largest_image_without_border_or_outline(self):
        theme = self.noir / "cursors/Oxygen-Noir-Sage"
        write_cursor(theme, [(10, 20, 30)] * 2 + [(100, 110, 120)] * 3 + [(200, 210, 220)] * 2)
        self.assertEqual(cr.cursor_colours(theme), [("Rim", "#0A141E", ""), ("Body", "#646E78", ""), ("Gloss", "#C8D2DC", "")])

    def test_a_broken_or_missing_cursor_has_no_colours(self):
        theme = self.noir / "cursors/Oxygen-Noir-Sage"
        self.assertEqual(cr.cursor_colours(theme), [])
        (theme / "cursors").mkdir()
        (theme / "cursors/left_ptr").write_bytes(b"Xcur")
        self.assertEqual(cr.cursor_colours(theme), [])

    def test_icon_colours_drop_repeats_and_keep_the_first_role(self):
        colours = cr.icon_colours("Cosmic-Noir-Sage")
        self.assertEqual(colours, [("Folder", "#88A57D", ""), ("Folder back", "#667C5E", ""), ("Symbol", "#171717", "")])

    def test_unknown_icon_pack_has_no_colours(self):
        self.assertEqual(cr.icon_colours("Cosmic-Nothing-Here"), [])

    def test_panel_shows_the_option_then_falls_back_to_the_rice(self):
        write_cursor(self.noir / "cursors/Oxygen-Noir-Sage", [(1, 100, 1)])
        c = self.choices()
        title, colours = c.panel("Cursors", "Sage")
        self.assertEqual((title, len(colours)), ("Sage", 3))
        self.assertEqual(c.panel("Cursors", "Orange")[0], "Noir")
        self.assertEqual(c.panel("Cursors", None)[0], "Noir")

    def test_keep_current_shows_the_option_in_use(self):
        (self.noir / "cosmic/config/com.system76.CosmicTk/v1/icon_theme").write_text('"Cosmic-Noir-Orange"')
        (self.conf / "cosmic/com.system76.CosmicTk/v1").mkdir(parents=True, exist_ok=True)
        (self.conf / "cosmic/com.system76.CosmicTk/v1/icon_theme").write_text('"Cosmic-Noir-Sage"')
        title, colours = self.choices().panel("Icons", None)
        self.assertEqual((title, colours[0][1]), ("Sage", "#88A57D"))

    def test_pair_shows_the_cursor_row_then_the_pick_then_what_flip_uses(self):
        c = self.choices()
        self.assertEqual(c.pair_shown("dark", "k3").slug, "k3")
        self.assertEqual(c.pair_shown("dark", None).slug, "noir")
        self.assertEqual(c.pair_shown("light", None).slug, "dossier")
        c.pick("Pair", "k3", "dark")
        self.assertEqual(c.pair_shown("dark", None).slug, "k3")


class Picking(TuiBase):
    def test_changing_rice_drops_picks_that_belonged_to_the_old_one(self):
        c = self.choices()
        c.pick("Wallpaper", cr.find_wallpaper(c.rice, "city"))
        c.pick("Cursors", "Sage")
        c.pick("Icons", "Sage")
        c.pick("Rice", cr.find(c.rices, "dossier"))
        self.assertEqual((c.wallpaper, c.cursor, c.icons), (None, None, None))

    def test_picking_the_same_rice_keeps_the_picks(self):
        c = self.choices()
        c.pick("Cursors", "Sage")
        c.pick("Rice", c.rice)
        self.assertEqual(c.cursor, "Sage")

    def test_pending_lists_everything_picked(self):
        c = self.choices()
        c.pick("Rice", cr.find(c.rices, "dossier"))
        c.pick("Wallpaper", cr.find_wallpaper(c.rice, "city"))
        c.pick("Cursors", "Sage")
        c.pick("Icons", "Orange")
        self.assertEqual(c.pending(), ["switch to Dossier", "wallpaper city", "cursor Sage", "icons Orange"])

    def test_a_half_pick_fills_in_the_rice_own_pair(self):
        c = self.choices()
        c.pick("Pair", "noir", "dark")
        self.assertEqual((c.dark, c.light), ("noir", "dossier"))
        self.assertIsNone(c.problem())

    def test_a_half_pick_with_no_pair_is_a_problem(self):
        (self.k3 / "README.md").write_text("# K3\n\n## Palette\n")
        (self.k3day / "README.md").write_text("# K3 Day\n\n## Palette\n")
        c = self.choices()
        c.pick("Pair", "k3", "dark")
        self.assertEqual(c.problem(), "Pair: pick a light rice too")

    def test_own_pair_row_clears_both_halves(self):
        cr.choose(self.rices(), "noir", "k3day")
        c = self.choices()
        self.assertEqual((c.dark, c.light), ("noir", "k3day"))
        c.pick("Pair", None, "light")
        self.assertEqual((c.dark, c.light), (None, None))
        self.assertEqual(c.pending(), ["flip own pairs"])

    def test_saved_pair_reads_the_same_whichever_order_it_was_chosen(self):
        cr.choose(self.rices(), "k3day", "noir")
        c = self.choices()
        self.assertEqual((c.dark, c.light), ("noir", "k3day"))
        self.assertEqual(c.pending(), [])


class Applying(TuiBase):
    def test_new_rice_changes_everything_live_and_keeps_icons(self):
        (self.conf / "cosmic/com.system76.CosmicTk/v1").mkdir(parents=True, exist_ok=True)
        icon = self.conf / "cosmic/com.system76.CosmicTk/v1/icon_theme"
        icon.write_text('"Mine"')
        (self.home / ".local/share/icons/Fake-Dossier-Orange").mkdir(parents=True)
        c = self.choices()
        c.pick("Rice", cr.find(c.rices, "dossier"))
        c.pick("Wallpaper", cr.find_wallpaper(c.rice, "city"))
        done, _ = self.apply(c)
        self.assertTrue(done)
        self.assertIn("cosmic-dossier-theme", self.active())
        self.assertTrue(self.wallpaper().endswith("dossier-city.png"))
        self.assertIn("cosmic-settings appearance import", self.log.read_text())
        self.assertEqual(icon.read_text(), '"Mine"')

    def test_wallpaper_on_the_active_rice_touches_nothing_else(self):
        c = self.choices()
        c.pick("Wallpaper", cr.find_wallpaper(c.rice, "city"))
        self.log.write_text("")
        done, _ = self.apply(c)
        self.assertTrue(done)
        self.assertTrue(self.wallpaper().endswith("noir-city.png"))
        self.assertEqual(self.log.read_text(), "")

    def test_pair_is_saved_without_switching(self):
        c = self.choices()
        before = self.active()
        c.pick("Pair", "noir", "dark")
        c.pick("Pair", "k3day", "light")
        done, out = self.apply(c)
        self.assertTrue(done)
        self.assertEqual(self.active(), before)
        self.assertEqual(cr.choice_file().read_text().split(), ["noir", "k3day"])
        self.assertIn("flip goes between noir and k3day", out)

    def test_own_pair_resets_the_choice(self):
        cr.choose(self.rices(), "noir", "k3day")
        c = self.choices()
        c.pick("Pair", None)
        self.apply(c)
        self.assertFalse(cr.choice_file().exists())

    def test_cursors_and_icons_run_their_installers_after_the_rice(self):
        c = self.choices()
        c.pick("Rice", cr.find(c.rices, "dossier"))
        c.pick("Cursors", "Sage")
        c.pick("Icons", "Orange")
        done, _ = self.apply(c)
        self.assertTrue(done)
        self.assertEqual(self.calls.read_text().splitlines(),
                         ["icons Dossier --variant Orange", "cursors Dossier --variant Sage"])

    def test_keeping_cursors_and_icons_runs_neither(self):
        c = self.choices()
        c.pick("Rice", cr.find(c.rices, "dossier"))
        self.apply(c)
        self.assertFalse(self.calls.exists())

    def test_a_failed_installer_is_reported_and_the_next_still_runs(self):
        script = self.noir / "icons/install.sh"
        script.write_text('#!/bin/sh\nexit 1\n')
        c = self.choices()
        c.pick("Icons", "Sage")
        c.pick("Cursors", "Sage")
        done, _ = self.apply(c)
        self.assertFalse(done)
        self.assertIn("cursors Noir --variant Sage", self.calls.read_text())


@unittest.skipUnless(shutil.which("infocmp") and subprocess.run(
    ["infocmp", "xterm-256color"], capture_output=True).returncode == 0, "needs the xterm-256color terminfo")
class RealScreen(TuiBase):
    """themebox.py itself on a pseudo-terminal, driven by the bytes a terminal sends."""

    def drive(self, *inputs, no_color=False):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
        env = {**os.environ, "THEMEBOX_REPOS": str(self.repos), "TERM": "xterm-256color"}
        env.pop("NO_COLOR", None)
        if no_color:
            env["NO_COLOR"] = "1"
        proc = subprocess.Popen([sys.executable, str(THEMEBOX)], stdin=slave, stdout=slave, stderr=slave,
                                env=env, start_new_session=True)
        os.close(slave)
        self.addCleanup(proc.kill)
        self.addCleanup(proc.wait)
        seen = b""
        waiting = list(inputs)
        end = time.monotonic() + 20
        settled = time.monotonic()
        while time.monotonic() < end:
            ready, _, _ = select.select([master], [], [], 0.05)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:  # the child closed the terminal
                    break
                if not chunk:
                    break
                seen += chunk
                settled = time.monotonic()
            elif waiting and b"themebox" in seen and time.monotonic() - settled > 0.05:
                os.write(master, waiting.pop(0).encode())
                settled = time.monotonic()
        os.close(master)
        self.assertEqual(proc.wait(timeout=5), 0, seen[-800:])
        return seen.decode(errors="replace")

    def test_keyboard_starts_on_the_active_rice_and_applies(self):
        self.drive("k", " ", "a")  # noir is last, one up is k3day
        self.assertIn("cosmic-k3day-theme", self.active())

    def test_up_stops_at_the_top_of_the_list(self):
        self.drive("k", "k", "k", "k", "k", " ", "a")
        self.assertIn("cosmic-dossier-theme", self.active())

    def test_quit_changes_nothing(self):
        before = self.active()
        self.drive("k", " ", "q")
        self.assertEqual(self.active(), before)

    def test_escape_quits(self):
        before = self.active()
        self.drive("k", " ", "\x1b")
        self.assertEqual(self.active(), before)

    def test_mouse_picks_a_rice_and_apply_button_applies(self):
        self.drive(click(10, 6), click(4, ROWS - 2))
        self.assertIn("cosmic-k3-theme", self.active())

    def test_mouse_opens_a_tab_and_picks_from_it(self):
        self.log.write_text("")
        self.drive(click(14, 2), click(10, 7), click(4, ROWS - 2))  # Wallpaper, the second file, Apply
        self.assertTrue(self.wallpaper().endswith("noir-city.png"))
        self.assertIn("cosmic-noir-theme", self.active())

    def test_mouse_picks_both_pair_columns(self):
        self.drive("3", click(5, 7), click(45, 8), click(4, ROWS - 2))  # k3 on the left, k3day on the right
        self.assertEqual(cr.choice_file().read_text().split(), ["k3", "k3day"])

    def test_apply_with_nothing_picked_stays_open_and_says_so(self):
        screen = self.drive(click(4, ROWS - 2), "\x1b")
        self.assertIn("Nothing to apply yet", screen)

    def test_rice_tab_paints_the_palette_of_the_row_under_the_cursor(self):
        screen = self.drive("q")
        self.assertIn("Noir palette", screen)
        self.assertIn("\x1b[48;2;23;23;23m", screen)
        self.assertIn("\x1b[48;2;242;86;35m", screen)
        self.assertNotIn("\x1b[48;2;208;208;200m", screen)

    def test_moving_the_cursor_changes_the_palette_without_picking(self):
        before = self.active()
        screen = self.drive("k", "k", "k", "q")  # up to dossier
        self.assertIn("Dossier palette", screen)
        self.assertIn("\x1b[48;2;208;208;200m", screen)
        self.assertEqual(self.active(), before)

    def test_cursor_row_shows_only_that_cursor_colours(self):
        write_cursor(self.noir / "cursors/Oxygen-Noir-Sage", [(0x80, 0x9F, 0x75)])
        screen = self.drive("4", "j", "j", "q").rsplit("\x1b7", 1)[1]  # the last frame painted
        self.assertIn("\x1b[48;2;128;159;117m", screen)
        self.assertNotIn("\x1b[48;2;23;23;23m", screen)

    def test_a_cursor_with_unknown_colours_shows_the_rice_palette(self):
        screen = self.drive("4", "j", "q").rsplit("\x1b7", 1)[1]  # Orange has no cursor folder here
        self.assertIn("\x1b[48;2;23;23;23m", screen)

    def test_cursors_tab_ignores_a_rice_only_browsed_to(self):
        screen = self.drive("k", "k", "k", "4", "q").rsplit("\x1b7", 1)[1]
        self.assertIn("\x1b[48;2;23;23;23m", screen)

    def test_wallpaper_tab_paints_nothing(self):
        self.assertEqual(self.drive("2", "q").count("\x1b7"), 1)  # only the Rice tab it opened on

    def test_pair_tab_paints_both_halves(self):
        screen = self.drive("3", "q")
        self.assertIn("\x1b[48;2;23;23;23m", screen)
        self.assertIn("\x1b[48;2;208;208;200m", screen)

    def test_no_color_paints_nothing(self):
        screen = self.drive("q", no_color=True)
        self.assertNotIn("48;2;", screen)

    def test_quit_button(self):
        before = self.active()
        self.drive("k", " ", click(13, ROWS - 2))
        self.assertEqual(self.active(), before)

    def test_terminal_is_left_with_mouse_reporting_off(self):
        self.assertIn("\x1b[?1006;1000l", self.drive("q"))


class Launch(TuiBase):
    def test_no_command_needs_a_terminal(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), unittest.mock.patch.dict(os.environ, {"THEMEBOX_REPOS": str(self.repos)}):
            code = cr.main([])
        self.assertEqual(code, 1)
        self.assertIn("need a terminal", err.getvalue())


class RealData(unittest.TestCase):
    """The table and cursors of the real rices, when they sit beside this repo."""
    repos = THEMEBOX.parent.parent

    def test_table_matches_cosmic_icon_themes(self):
        source = self.repos / "cosmic-icon-themes"
        if not source.is_dir():
            self.skipTest("needs cosmic-icon-themes beside this repo")
        code = ("import pathlib, sys, tomllib\nsys.dont_write_bytecode = True\nsys.path.insert(0, sys.argv[1])\n"
                "import icon_palettes\n"
                "assert icon_palettes.packs(pathlib.Path(sys.argv[2])) == tomllib.loads(pathlib.Path(sys.argv[3]).read_text())")
        subprocess.run([sys.executable, "-c", code, str(THEMEBOX.parent / "tools"), str(source),
                        str(THEMEBOX.parent / "icon-palettes.toml")], check=True)

    def test_every_option_of_every_rice_has_colours(self):
        rices = [r for r in cr.discover(self.repos) if (r.repo / "cursors").is_dir()]
        if not rices:
            self.skipTest("needs the rices beside this repo")
        for rice in rices:
            for option in cr.variants(rice, "cursors"):
                theme = rice.repo / "cursors" / cr.cursor_name(rice, option)
                self.assertEqual(len(cr.cursor_colours(theme)), 3, (rice.slug, option))
            for option in cr.variants(rice, "icons"):
                self.assertTrue(cr.icon_colours(cr.icon_name(rice, option)), (rice.slug, option))


if __name__ == "__main__":
    unittest.main()
