"""A rice somebody made themselves: rice.toml and whatever tools they use."""
import contextlib
import io
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import themebox as cr  # noqa: E402
from test_flip import FlipBase  # noqa: E402


class OwnBase(FlipBase):
    def setUp(self):
        super().setUp()
        self.mine = self.own("mine", 'name = "Mine"\nmode = "dark"\ntheme = "Mine.ron"\npair = "mineday"\n')
        self.day = self.own("mineday", 'name = "Mine Day"\nmode = "light"\ntheme = "MineDay.ron"\npair = "mine"\n')
        (self.mine / "cosmic/Mine.ron").write_text("()")
        (self.day / "cosmic/MineDay.ron").write_text("()")

    def own(self, slug, toml):
        repo = self.repos / f"cosmic-{slug}-theme"
        (repo / "cosmic").mkdir(parents=True)
        (repo / "rice.toml").write_text(toml)
        return repo


class Settings(OwnBase):
    def test_reads_rice_toml(self):
        r = cr.find(self.rices(), "mine")
        self.assertEqual((r.name, r.slug, r.mode, r.ron, r.pair), ("Mine", "mine", "dark", "Mine.ron", "mineday"))

    def test_optional_settings_are_empty(self):
        r = cr.find(self.rices(), "mine")
        self.assertEqual((r.term_ron, r.btop), ("", ""))

    def test_reads_the_optional_settings(self):
        with (self.mine / "rice.toml").open("a") as f:
            f.write('terminal = "Mine-term.ron"\nbtop = "Mine"\n')
        r = cr.find(self.rices(), "mine")
        self.assertEqual((r.term_ron, r.btop), ("Mine-term.ron", "Mine"))

    def test_rice_toml_wins_over_switch_sh(self):
        (self.noir / "rice.toml").write_text('name = "Noir Two"\nmode = "dark"\ntheme = "Noir.ron"\n')
        self.assertEqual(cr.find(self.rices(), "noir").name, "Noir Two")

    def test_older_rice_still_reads_switch_sh(self):
        self.assertEqual(cr.find(self.rices(), "noir").name, "Noir")

    def test_pair_in_one_file_is_enough(self):
        (self.day / "rice.toml").write_text('name = "Mine Day"\nmode = "light"\ntheme = "MineDay.ron"\n')
        self.assertEqual(cr.find(self.rices(), "mineday").pair, "mine")

    def test_missing_setting_names_the_file_and_the_setting(self):
        (self.mine / "rice.toml").write_text('name = "Mine"\nmode = "dark"\n')
        with self.assertRaisesRegex(cr.Error, r"cosmic-mine-theme.*theme"):
            self.rices()

    def test_bad_mode_is_refused(self):
        (self.mine / "rice.toml").write_text('name = "Mine"\nmode = "dusk"\ntheme = "Mine.ron"\n')
        with self.assertRaisesRegex(cr.Error, "dusk"):
            self.rices()

    def test_broken_toml_is_an_error_not_a_crash(self):
        (self.mine / "rice.toml").write_text("name = \n")
        with self.assertRaisesRegex(cr.Error, "rice.toml"):
            self.rices()

    def test_switch_sh_missing_a_setting_is_an_error_not_a_crash(self):
        script = self.noir / "scripts/switch.sh"
        script.write_text(script.read_text().replace('BTOP="Noir"\n', ""))
        with self.assertRaisesRegex(cr.Error, "BTOP"):
            self.rices()


class Get(OwnBase):
    def get(self):
        fetched = []
        with unittest.mock.patch.object(cr, "fetch", side_effect=lambda _, name: fetched.append(name)), \
                contextlib.redirect_stdout(io.StringIO()):
            cr.get(self.repos, "mine")
        return fetched

    def test_follows_the_pair_in_rice_toml(self):
        self.assertEqual(self.get(), ["cosmic-mine-theme", "cosmic-mineday-theme"])

    def test_a_pair_that_is_not_a_rice_name_is_refused(self):
        (self.mine / "rice.toml").write_text('name = "M"\nmode = "dark"\ntheme = "M.ron"\npair = "../../evil"\n')
        with self.assertRaisesRegex(cr.Error, "evil"):
            self.get()


class Skipping(OwnBase):
    def test_switch_succeeds_with_only_a_theme(self):
        ok, out = self.switch("mine")
        self.assertTrue(ok, out)
        self.assertEqual(cr.active(self.rices()).slug, "mine")

    def test_no_zsh_folder_leaves_zshrc_alone(self):
        before = (self.home / ".zshrc").read_text()
        self.switch("mine")
        self.assertEqual((self.home / ".zshrc").read_text(), before)

    def test_no_nvim_folder_leaves_other_specs_alone(self):
        self.switch("mine")
        self.assertTrue((self.conf / "nvim/lua/plugins/noir.lua").is_file())

    def test_a_tool_that_is_there_still_runs(self):
        (self.mine / "starship").mkdir()
        script = self.mine / "starship/install.sh"
        script.write_text('#!/bin/sh\necho "ran starship"\n')
        script.chmod(0o755)
        self.assertIn("ran starship", self.switch("mine")[1])

    def test_a_tool_that_fails_still_counts_as_failed(self):
        (self.mine / "starship").mkdir()
        script = self.mine / "starship/install.sh"
        script.write_text("#!/bin/sh\nexit 1\n")
        script.chmod(0o755)
        self.assertFalse(self.switch("mine")[0])

    def test_a_btop_theme_that_is_named_but_missing_fails(self):
        with (self.mine / "rice.toml").open("a") as f:
            f.write('btop = "Mine"\n')
        self.assertFalse(self.switch("mine")[0])

    def test_steps_only_name_what_the_rice_has(self):
        out = self.switch("mine")[1]
        self.assertIn("Import cosmic/Mine.ron", out)
        for word in ("Firefox", "COSMIC Terminal", "Claude", "zsh", "Neovim", "Cursor"):
            self.assertNotIn(word, out)

    def test_steps_are_numbered_without_gaps(self):
        self.assertRegex(self.switch("noir")[1], r"(?s)  1\. .*  2\. .*  3\. ")
        self.assertNotIn("  2. ", self.switch("mine")[1])

    def test_full_rice_keeps_its_steps(self):
        out = self.switch("noir")[1]
        for word in ("Firefox", "Claude Desktop", "exec zsh", "restart Neovim"):
            self.assertIn(word, out)

    def test_flip_between_two_minimal_rices(self):
        self.switch("mine", steps=False)
        ok, out = self.flip()
        self.assertTrue(ok, out)
        self.assertIn("MineDay.ron", self.stub_log())
        self.assertNotIn("Firefox", out)
        self.assertNotIn("install-shell", out)

    def test_flip_comes_back_with_no_update_script(self):
        self.switch("mine", steps=False)
        self.flip()
        self.flip()
        self.assertEqual(cr.active(self.rices()).slug, "mine")


class UpdateLink(OwnBase):
    def test_a_real_update_script_is_backed_up(self):
        link = self.home / "update_system.sh"
        link.unlink()
        link.write_text("my own script\n")
        self.switch("noir")
        self.assertEqual((self.home / "update_system.sh.bak").read_text(), "my own script\n")


if __name__ == "__main__":
    unittest.main()
