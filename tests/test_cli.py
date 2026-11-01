"""Behaviour of themebox against small fake rice repos in a temp HOME."""
import contextlib
import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import themebox as cr  # noqa: E402

INSTALLER = '#!/usr/bin/env bash\nset -e\necho "ran {tool}"\n{extra}'


def fake_rice(repos, slug, name, mode, pair):
    r = repos / f"cosmic-{slug}-theme"
    (r / "scripts").mkdir(parents=True)
    (r / "scripts/switch.sh").write_text(
        f'#!/usr/bin/env bash\nNAME="{name}"   # shown\nSLUG="{slug}"\nMODE="{mode}"\n'
        f'RON="{name}.ron"\nTERM_RON="{name}-term.ron"\nBTOP="{name}"\n')
    (r / "scripts/update_system.sh").write_text("#!/bin/sh\n")
    half = "dark" if mode == "light" else "light"
    (r / "README.md").write_text(
        f"# COSMIC · {name}\n\nThe {mode} half; the {half} half is "
        f"[x](https://github.com/atraxsrc/cosmic-{pair}-theme).\n\n## Palette\n")
    cfg = r / "cosmic/config/com.system76.CosmicTerm/v1"
    cfg.mkdir(parents=True)
    (cfg / "syntax_theme_dark").write_text(f'"{name}"')
    (cfg / "syntax_theme_light").write_text(f'"{name}"')
    (cfg / "font_size").write_text("14")
    tk = r / "cosmic/config/com.system76.CosmicTk/v1"
    tk.mkdir(parents=True)
    (tk / "icon_theme").write_text(f'"Kanagawa-{name}-Orange"')
    (r / "btop").mkdir()
    (r / f"btop/{name}.theme").write_text("theme\n")
    (r / "claude-desktop").mkdir()
    (r / f"claude-desktop/{slug}.jsonc").write_text("{}\n")
    nvim = f'mkdir -p "$HOME/.config/nvim/lua/plugins"\ntouch "$HOME/.config/nvim/lua/plugins/{slug}.lua"\n'
    zsh = f'echo "source {r}/zsh/{slug}.zsh" >> "$HOME/.zshrc"\n'
    for tool, extra in (("nvim", nvim), ("zsh", zsh), ("firefox", ""), ("claude-desktop", ""), ("bat", "")):
        d = r / tool
        d.mkdir(exist_ok=True)
        f = d / "install.sh"
        f.write_text(INSTALLER.format(tool=tool, extra=extra))
        f.chmod(f.stat().st_mode | stat.S_IXUSR)
    return r


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.repos = self.root / "repos"
        self.home = self.root / "home"
        self.home.mkdir()
        self.conf = self.home / ".config"
        env = {"HOME": str(self.home)}
        patch = unittest.mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.noir = fake_rice(self.repos, "noir", "Noir", "dark", "dossier")
        self.dossier = fake_rice(self.repos, "dossier", "Dossier", "light", "noir")
        self.k3 = fake_rice(self.repos, "k3", "K3", "dark", "k3day")
        self.k3day = fake_rice(self.repos, "k3day", "K3 Day", "light", "k3")

    def rices(self):
        return cr.discover(self.repos)

    def switch(self, slug, **kw):
        rices = self.rices()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = cr.switch(cr.find(rices, slug), rices, **kw)
        return ok, buf.getvalue()

    def is_dark(self):
        return (self.conf / "cosmic/com.system76.CosmicTheme.Mode/v1/is_dark")


class Discover(Base):
    def test_reads_settings_block(self):
        r = cr.find(self.rices(), "noir")
        self.assertEqual((r.name, r.mode, r.ron, r.term_ron, r.btop), ("Noir", "dark", "Noir.ron", "Noir-term.ron", "Noir"))

    def test_finds_pair_from_readme(self):
        self.assertEqual(cr.find(self.rices(), "noir").pair, "dossier")

    def test_ignores_dirs_without_switch_settings(self):
        (self.repos / "cosmic-icon-themes").mkdir()
        self.assertEqual(len(self.rices()), 4)

    def test_find_accepts_display_name(self):
        self.assertEqual(cr.find(self.rices(), "K3 Day").slug, "k3day")

    def test_find_unknown_names_the_slug(self):
        with self.assertRaisesRegex(cr.Error, "nope"):
            cr.find(self.rices(), "nope")


class Active(Base):
    def test_none_without_link(self):
        self.assertIsNone(cr.active(self.rices()))

    def test_follows_update_link(self):
        self.switch("dossier")
        self.assertEqual(cr.active(self.rices()).slug, "dossier")


class Switch(Base):
    def test_copies_cosmic_config_and_sets_mode(self):
        self.assertTrue(self.switch("noir")[0])
        self.assertEqual((self.conf / "cosmic/com.system76.CosmicTerm/v1/font_size").read_text(), "14")
        self.assertEqual(self.is_dark().read_text().strip(), "true")
        self.switch("dossier")
        self.assertEqual(self.is_dark().read_text().strip(), "false")

    def test_only_this_modes_terminal_scheme_is_written(self):
        self.switch("noir")
        d = self.conf / "cosmic/com.system76.CosmicTerm/v1"
        self.assertTrue((d / "syntax_theme_dark").exists())
        self.assertFalse((d / "syntax_theme_light").exists())

    def test_dimmed_variant_of_scheme_is_kept(self):
        d = self.conf / "cosmic/com.system76.CosmicTerm/v1"
        d.mkdir(parents=True)
        (d / "syntax_theme_dark").write_text('"Noir Dim"')
        self.switch("noir")
        self.assertEqual((d / "syntax_theme_dark").read_text(), '"Noir Dim"')

    def test_backs_up_replaced_config(self):
        d = self.conf / "cosmic/com.system76.CosmicTerm/v1"
        d.mkdir(parents=True)
        (d / "font_size").write_text("11")
        self.switch("noir")
        self.assertEqual((d / "font_size.bak").read_text(), "11")

    def test_icons_left_alone_when_not_installed(self):
        _, out = self.switch("noir")
        self.assertFalse((self.conf / "cosmic/com.system76.CosmicTk/v1/icon_theme").exists())
        self.assertIn("not installed", out)

    def test_icons_applied_when_installed(self):
        (self.home / ".local/share/icons/Kanagawa-Noir-Orange").mkdir(parents=True)
        self.switch("noir")
        self.assertIn("Kanagawa-Noir-Orange", (self.conf / "cosmic/com.system76.CosmicTk/v1/icon_theme").read_text())

    def test_another_folder_colour_of_same_pack_is_kept(self):
        (self.home / ".local/share/icons/Kanagawa-Noir-Orange").mkdir(parents=True)
        f = self.conf / "cosmic/com.system76.CosmicTk/v1/icon_theme"
        f.parent.mkdir(parents=True)
        f.write_text('"Kanagawa-Noir-Sage"')
        self.switch("noir")
        self.assertEqual(f.read_text(), '"Kanagawa-Noir-Sage"')

    def test_keep_icons(self):
        (self.home / ".local/share/icons/Kanagawa-Noir-Orange").mkdir(parents=True)
        self.switch("noir", keep_icons=True)
        self.assertFalse((self.conf / "cosmic/com.system76.CosmicTk/v1/icon_theme").exists())

    def test_btop_conf_points_at_theme(self):
        (self.conf / "btop").mkdir(parents=True)
        (self.conf / "btop/btop.conf").write_text('color_theme = "old"\nother = 1\n')
        self.switch("noir")
        self.assertEqual((self.conf / "btop/btop.conf").read_text(), 'color_theme = "Noir"\nother = 1\n')
        self.assertTrue((self.conf / "btop/themes/Noir.theme").exists())

    def test_every_other_rices_nvim_spec_is_parked(self):
        plugins = self.conf / "nvim/lua/plugins"
        plugins.mkdir(parents=True)
        (plugins / "k3day.lua").touch()  # switch.sh missed this: its list was never complete
        (plugins / "harbordark.lua").touch()
        (plugins / "keymaps.lua").touch()
        self.switch("noir")
        self.assertEqual(sorted(p.name for p in plugins.iterdir()), ["keymaps.lua", "noir.lua"])
        self.assertEqual(sorted(p.name for p in (self.conf / "nvim/rice-off").iterdir()), ["harbordark.lua", "k3day.lua"])

    def test_zsh_comments_out_a_slug_with_a_digit(self):
        rc = self.home / ".zshrc"
        rc.write_text(f"source {self.k3}/zsh/k3.zsh\n")
        self.switch("noir")
        self.assertIn(f"# source {self.k3}/zsh/k3.zsh", rc.read_text())

    def test_zsh_uncomments_this_rice_without_reinstalling(self):
        rc = self.home / ".zshrc"
        rc.write_text(f"export A=1\n# source {self.noir}/zsh/noir.zsh\nsource {self.dossier}/zsh/dossier.zsh\n")
        self.switch("noir")
        self.assertEqual(rc.read_text(), f"export A=1\nsource {self.noir}/zsh/noir.zsh\n# source {self.dossier}/zsh/dossier.zsh\n")
        self.assertTrue((self.home / ".zshrc.bak").exists())

    def test_zsh_installs_when_rc_has_no_line(self):
        self.switch("noir")
        self.assertIn(f"source {self.noir}/zsh/noir.zsh", (self.home / ".zshrc").read_text())

    def test_old_ricing_colors_line_is_commented(self):
        rc = self.home / ".zshrc"
        rc.write_text("source ~/ricing/zsh/colors.zsh\n")
        self.switch("noir")
        self.assertIn("# source ~/ricing/zsh/colors.zsh", rc.read_text())

    def test_failed_installer_does_not_stop_the_rest_and_reports_false(self):
        (self.noir / "bat/install.sh").write_text("#!/usr/bin/env bash\nexit 3\n")
        ok, out = self.switch("noir")
        self.assertFalse(ok)
        self.assertIn("bat", out.split("failed")[-1])
        self.assertEqual(cr.active(self.rices()).slug, "noir")

    def test_missing_btop_theme_does_not_stop_the_rest(self):
        (self.noir / "btop/Noir.theme").unlink()
        ok, out = self.switch("noir")
        self.assertFalse(ok)
        self.assertIn("btop", out.split("failed")[-1])
        self.assertEqual(cr.active(self.rices()).slug, "noir")

    def test_backups_keep_the_private_mode_of_the_original(self):
        rc = self.home / ".zshrc"
        rc.touch(mode=0o600)
        conf = self.conf / "btop/btop.conf"
        conf.parent.mkdir(parents=True)
        conf.write_text('color_theme = "old"\n')
        conf.chmod(0o600)
        font = self.conf / "cosmic/com.system76.CosmicTerm/v1/font_size"
        font.parent.mkdir(parents=True)
        font.write_text("11")
        font.chmod(0o600)
        self.switch("noir")
        for original in (rc, conf, font):
            bak = original.with_name(original.name + ".bak")
            self.assertEqual(stat.S_IMODE(bak.stat().st_mode), 0o600, bak.name)

    def test_stale_open_backup_is_tightened(self):
        rc = self.home / ".zshrc"
        rc.touch(mode=0o600)
        bak = self.home / ".zshrc.bak"
        bak.touch(mode=0o644)
        self.switch("noir")
        self.assertEqual(stat.S_IMODE(bak.stat().st_mode), 0o600)

    def test_firefox_failure_is_only_a_skip(self):
        (self.noir / "firefox/install.sh").write_text("#!/usr/bin/env bash\nexit 1\n")
        ok, out = self.switch("noir")
        self.assertTrue(ok)
        self.assertIn("firefox: skipped", out)

    def test_prints_gui_steps_unless_quiet(self):
        self.assertIn("Import cosmic/Noir.ron", self.switch("noir")[1])
        self.assertNotIn("Import cosmic/Noir.ron", self.switch("noir", steps=False)[1])

    def test_day_steps_name_the_light_tab(self):
        self.assertIn("Appearance → Light", self.switch("dossier")[1])


class Pair(Base):
    def follow(self):
        rices = self.rices()
        with contextlib.redirect_stdout(io.StringIO()):
            return cr.follow(rices)

    def test_toggle_moves_to_the_other_half(self):
        self.switch("noir")
        self.is_dark().write_text("false\n")
        self.assertEqual(self.follow().slug, "dossier")
        self.assertEqual(cr.active(self.rices()).slug, "dossier")

    def test_nothing_happens_when_already_matching(self):
        self.switch("noir")
        self.assertIsNone(self.follow())

    def test_no_active_rice_is_an_error(self):
        self.is_dark().parent.mkdir(parents=True)
        self.is_dark().write_text("true\n")
        with self.assertRaisesRegex(cr.Error, "active"):
            self.follow()

    def test_toggle_keeps_written_mode(self):
        self.switch("noir")
        self.is_dark().write_text("false\n")
        self.follow()
        self.assertEqual(self.is_dark().read_text().strip(), "false")


class Cli(Base):
    def run_main(self, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), unittest.mock.patch.dict(os.environ, {"THEMEBOX_REPOS": str(self.repos)}):
            code = cr.main(list(argv))
        return code, buf.getvalue()

    def test_list_marks_the_active_rice(self):
        self.run_main("switch", "noir")
        code, out = self.run_main("list")
        self.assertEqual(code, 0)
        marked = [x for x in out.splitlines() if x.startswith("*")]
        self.assertEqual(len(marked), 1)
        self.assertEqual(marked[0].split()[1::3], ["noir", "dossier"])
        self.assertEqual(len(out.strip().splitlines()), 4)

    def test_relative_repos_folder_still_writes_an_absolute_link(self):
        os.chdir(self.root)
        self.addCleanup(os.chdir, Path(__file__).resolve().parent.parent)
        with unittest.mock.patch.dict(os.environ, {"THEMEBOX_REPOS": "repos"}), \
                contextlib.redirect_stdout(io.StringIO()):
            cr.main(["switch", "noir"])
        self.assertTrue(os.readlink(self.home / "update_system.sh").startswith("/"))

    def test_runs_through_a_symlink_like_the_installed_command(self):
        (self.root / "bin").mkdir()
        link = self.root / "bin/themebox"
        link.symlink_to(Path(cr.__file__).resolve())
        env = {k: v for k, v in os.environ.items() if k != "THEMEBOX_REPOS"}
        done = subprocess.run([str(link), "list"], env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_unknown_slug_exits_nonzero(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            self.assertEqual(self.run_main("switch", "nope")[0], 1)
        self.assertIn("nope", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
