"""themebox flip, with stub desktop commands first on PATH."""
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
import themebox as cr  # noqa: E402
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
        return cr.pick_wallpaper(cr.find(rices, "dossier"))

    def test_anime_wins_even_when_the_other_half_has_the_same_subject(self):
        self.assertEqual(self.pick(f"{self.noir}/backgrounds/noir-city.png").name, "dossier-anime.png")

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

    def current(self):
        return cr.WALLPAPER.search((self.bg / "all").read_text()).group(1)

    def test_round_trip_returns_to_the_wallpaper_you_left(self):
        mine = self.noir / "backgrounds/noir-anime-2.png"
        mine.touch()
        (self.bg / "all").write_text(ALL.replace("/old/place/wall.png", str(mine)))
        self.flip()
        self.assertEqual(self.current(), str(self.dossier / "backgrounds/dossier-anime.png"))
        self.flip()
        self.assertEqual(self.current(), str(mine))

    def test_a_wallpaper_from_anywhere_is_remembered_too(self):
        mine = self.root / "my.png"
        mine.touch()
        (self.bg / "all").write_text(ALL.replace("/old/place/wall.png", str(mine)))
        self.flip()
        self.flip()
        self.assertEqual(self.current(), str(mine))

    def test_a_remembered_file_that_is_gone_falls_back(self):
        mine = self.root / "my.png"
        mine.touch()
        (self.bg / "all").write_text(ALL.replace("/old/place/wall.png", str(mine)))
        self.flip()
        mine.unlink()
        self.flip()
        self.assertEqual(self.current(), str(self.noir / "backgrounds/noir-anime.png"))

    def test_separate_monitors_become_a_manual_step(self):
        (self.bg / "same-on-all").write_text("false")
        rices = self.rices()
        msgs = cr.apply_wallpaper(cr.find(rices, "dossier"), cr.find(rices, "noir"))
        self.assertEqual((self.bg / "all").read_text(), ALL)
        self.assertIn("Wallpaper", msgs[0])


class Choosing(FlipBase):
    def current(self):
        return cr.WALLPAPER.search((self.bg / "all").read_text()).group(1)

    def wall(self, repo, slug, subject):
        return str(repo / f"backgrounds/{slug}-{subject}.png")

    def main(self, *args, answers=()):
        env = {"THEMEBOX_REPOS": str(self.repos)}
        with unittest.mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()) as out, \
                unittest.mock.patch("builtins.input", side_effect=list(answers) or EOFError):
            code = cr.main(list(args))
        return code, out.getvalue()

    def test_list_shows_short_names_and_marks_the_one_in_use(self):
        (self.bg / "all").write_text(ALL.replace("/old/place/wall.png", self.wall(self.noir, "noir", "city")))
        code, out = self.main("wallpaper", "noir")
        self.assertEqual(code, 0)
        self.assertEqual(out.split("\n")[:2], ["  anime", "* city"])

    def test_saving_for_the_active_rice_changes_it_now(self):
        self.assertEqual(self.main("wallpaper", "noir", "city")[0], 0)
        self.assertEqual(self.current(), self.wall(self.noir, "noir", "city"))

    def test_saving_for_another_rice_waits_for_the_flip(self):
        self.main("wallpaper", "dossier", "city")
        self.assertEqual(self.current(), "/old/place/wall.png")
        self.flip()
        self.assertEqual(self.current(), self.wall(self.dossier, "dossier", "city"))

    def test_list_marks_the_saved_one_for_another_rice(self):
        self.main("wallpaper", "dossier", "city")
        self.assertEqual(self.main("wallpaper", "dossier")[1].split("\n")[:2], ["  anime", "* city"])

    def test_saved_wallpaper_survives_a_round_trip(self):
        self.main("wallpaper", "noir", "city")
        self.flip()
        self.flip()
        self.assertEqual(self.current(), self.wall(self.noir, "noir", "city"))

    def test_unknown_wallpaper_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.main("wallpaper", "noir", "nope")[0], 1)
        self.assertIn("nope", err.getvalue())

    def test_switch_applies_the_saved_wallpaper(self):
        self.main("wallpaper", "dossier", "city")
        self.assertEqual(self.main("switch", "dossier")[0], 0)
        self.assertEqual(self.current(), self.wall(self.dossier, "dossier", "city"))

    def test_switch_with_nothing_saved_picks_like_flip(self):
        self.main("switch", "dossier")
        self.assertEqual(self.current(), self.wall(self.dossier, "dossier", "anime"))

    def test_switch_remembers_the_wallpaper_it_left(self):
        self.main("wallpaper", "noir", "city")
        self.main("switch", "dossier")
        self.main("switch", "noir")
        self.assertEqual(self.current(), self.wall(self.noir, "noir", "city"))

    def test_switch_to_the_active_rice_keeps_the_wallpaper(self):
        self.main("switch", "noir")
        self.assertEqual(self.current(), "/old/place/wall.png")

    def test_first_switch_with_no_active_rice_works(self):
        (self.home / "update_system.sh").unlink()
        self.assertEqual(self.main("switch", "dossier")[0], 0)
        self.assertEqual(self.current(), self.wall(self.dossier, "dossier", "anime"))

    def test_switch_no_longer_lists_wallpaper_as_a_step(self):
        self.assertNotIn("Settings → Wallpaper", self.main("switch", "dossier")[1])

    def test_switch_says_so_when_it_cannot_set_the_wallpaper(self):
        (self.bg / "same-on-all").write_text("false")
        self.assertIn("Settings → Wallpaper", self.main("switch", "dossier")[1])

    def test_switch_pick_uses_the_number_typed(self):
        self.main("switch", "dossier", "--pick", answers=["2"])
        self.assertEqual(self.current(), self.wall(self.dossier, "dossier", "city"))

    def test_flip_pick_uses_the_number_typed(self):
        self.main("flip", "--pick", answers=["2"])
        self.assertEqual(self.current(), self.wall(self.dossier, "dossier", "city"))

    def test_pick_accepts_a_name_and_asks_again_after_a_bad_answer(self):
        self.main("switch", "dossier", "--pick", answers=["9", "city"])
        self.assertEqual(self.current(), self.wall(self.dossier, "dossier", "city"))

    def test_pick_enter_keeps_the_saved_one(self):
        self.main("wallpaper", "dossier", "city")
        self.main("switch", "dossier", "--pick", answers=[""])
        self.assertEqual(self.current(), self.wall(self.dossier, "dossier", "city"))

    def test_pick_without_a_terminal_is_refused_before_anything_changes(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.main("switch", "dossier", "--pick")[0], 1)
        self.assertIn("terminal", err.getvalue())
        self.assertEqual(cr.active(self.rices()).slug, "noir")

    def test_pick_with_no_backgrounds_does_not_ask(self):
        for f in (self.dossier / "backgrounds").iterdir():
            f.unlink()
        self.assertEqual(self.main("switch", "dossier", "--pick")[0], 0)


class Report(FlipBase):
    def test_report_lists_firefox_and_goes_to_notify_send(self):
        _, out = self.flip()
        self.assertIn("Firefox", out)
        sent = self.stub_log().split("notify-send", 1)[1]
        self.assertIn("Firefox", sent)
        self.assertIn("Dossier is active", sent)

    def test_firefox_step_says_to_restart(self):
        self.assertIn("restart Firefox", cr.leftovers(cr.find(self.rices(), "dossier"))[0])

    def test_shared_claude_theme_is_not_a_step(self):
        self.assertFalse(any("Claude" in m for m in cr.leftovers(cr.find(self.rices(), "dossier"))))

    def test_missing_icon_pack_is_a_step(self):
        rice = cr.find(self.rices(), "dossier")
        step = [m for m in cr.leftovers(rice) if m.startswith("Icons")]
        self.assertIn(f"{rice.repo}/icons/install.sh", step[0])
        (self.home / ".local/share/icons/Kanagawa-Dossier-Orange").mkdir(parents=True)
        self.assertFalse(any(m.startswith("Icons") for m in cr.leftovers(rice)))

    def test_flip_shows_only_the_report(self):
        self.assertNotIn("ran bat", self.flip()[1])

    def test_flip_shows_installer_output_when_a_tool_fails(self):
        (self.dossier / "bat/install.sh").write_text("#!/bin/sh\necho bat is broken\nexit 3\n")
        ok, out = self.flip()
        self.assertFalse(ok)
        self.assertIn("bat is broken", out)

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
        env = {"THEMEBOX_REPOS": str(self.repos)}
        with unittest.mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cr.main(["flip"]), 0)
            self.assertEqual(cr.active(self.rices()).slug, "dossier")
            self.stub("cosmic-settings", "", code=1)
            self.assertEqual(cr.main(["flip"]), 1)


class Choose(FlipBase):
    def setUp(self):
        super().setUp()
        (self.k3day / "cosmic/K3 Day.ron").write_text("()")

    def test_flip_goes_between_the_chosen_two(self):
        cr.choose(self.rices(), "noir", "k3day")
        self.flip()
        self.assertEqual(cr.active(self.rices()).slug, "k3day")
        self.flip()
        self.assertEqual(cr.active(self.rices()).slug, "noir")

    def test_order_does_not_matter(self):
        cr.choose(self.rices(), "k3day", "noir")
        self.assertEqual(cr.partner(cr.find(self.rices(), "noir"), self.rices()).slug, "k3day")

    def test_rice_outside_the_choice_keeps_its_own_pair(self):
        cr.choose(self.rices(), "noir", "k3day")
        self.switch("k3", steps=False)
        self.assertEqual(cr.partner(cr.find(self.rices(), "k3"), self.rices()).slug, "k3day")
        self.switch("dossier", steps=False)
        self.assertEqual(cr.partner(cr.find(self.rices(), "dossier"), self.rices()).slug, "noir")

    def test_two_of_the_same_mode_are_refused(self):
        with self.assertRaisesRegex(cr.Error, "one dark and one light"):
            cr.choose(self.rices(), "noir", "k3")

    def test_unknown_rice_is_refused(self):
        with self.assertRaisesRegex(cr.Error, "nope"):
            cr.choose(self.rices(), "noir", "nope")

    def test_reset_goes_back_to_the_real_pair(self):
        cr.choose(self.rices(), "noir", "k3day")
        cr.reset_choice()
        self.assertEqual(cr.partner(cr.find(self.rices(), "noir"), self.rices()).slug, "dossier")

    def test_a_choice_naming_a_removed_rice_is_ignored(self):
        cr.choose(self.rices(), "noir", "k3day")
        import shutil
        shutil.rmtree(self.k3day)
        self.assertEqual(cr.partner(cr.find(self.rices(), "noir"), self.rices()).slug, "dossier")

    def test_pair_follows_the_choice(self):
        cr.choose(self.rices(), "noir", "k3day")
        self.is_dark().write_text("false\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cr.follow(self.rices()).slug, "k3day")

    def test_command_sets_and_resets(self):
        env = {"THEMEBOX_REPOS": str(self.repos)}
        with unittest.mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cr.main(["choose", "noir", "k3day"]), 0)
            self.assertEqual(cr.partner(cr.find(self.rices(), "noir"), self.rices()).slug, "k3day")
            self.assertEqual(cr.main(["choose", "--reset"]), 0)
            self.assertEqual(cr.partner(cr.find(self.rices(), "noir"), self.rices()).slug, "dossier")
        self.assertIn("k3day", out.getvalue())


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
