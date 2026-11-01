"""cosmic-rice get against local git repos, and install.sh with a stub curl."""
import contextlib
import hashlib
import io
import os
import stat
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cosmic_rice as cr  # noqa: E402
from test_cli import Base, fake_rice  # noqa: E402

ROOT = Path(cr.__file__).resolve().parent
ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def git(*args, cwd):
    subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=True,
                   capture_output=True, env={**os.environ, **ENV})


class Get(Base):
    def setUp(self):
        super().setUp()
        self.upstream = self.repos  # the fake rices play GitHub
        for repo in (self.noir, self.dossier):
            git("init", "-q", "-b", "master", cwd=repo)
            git("add", "-A", cwd=repo)
            git("commit", "-qm", "x", cwd=repo)
        self.empty = self.root / "fresh"
        self.empty.mkdir()
        patch = unittest.mock.patch.object(cr, "SOURCE", f"file://{self.upstream}")
        patch.start()
        self.addCleanup(patch.stop)
        env = unittest.mock.patch.dict(os.environ, {"COSMIC_RICE_REPOS": str(self.empty), **ENV})
        env.start()
        self.addCleanup(env.stop)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cr.main(list(argv))
            except SystemExit as exit_:  # argparse refusing an option-like argument
                code = exit_.code
        return code, out.getvalue() + err.getvalue()

    def test_get_downloads_the_rice_and_its_other_half(self):
        code, out = self.main("get", "noir")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(p.name for p in self.empty.iterdir()),
                         ["cosmic-dossier-theme", "cosmic-noir-theme"])
        self.assertIn("cosmic-rice switch noir", out)

    def test_get_works_from_nothing_and_list_then_sees_them(self):
        self.assertEqual(self.main("list")[0], 1)
        self.main("get", "noir")
        code, out = self.main("list")
        self.assertEqual(code, 0)
        self.assertIn("dossier", out)

    def test_a_second_get_changes_nothing(self):
        self.main("get", "noir")
        code, out = self.main("get", "noir")
        self.assertEqual(code, 0, out)
        self.assertIn("already", out)

    def test_unknown_rice_is_a_clear_error(self):
        code, out = self.main("get", "nope")
        self.assertEqual(code, 1)
        self.assertIn("nope", out)
        self.assertEqual(list(self.empty.iterdir()), [])

    def test_a_slug_cannot_escape_the_repo_name(self):
        for bad in ("../x", "a/b", "-oProxyCommand=x", ""):
            code, out = self.main("get", bad)
            self.assertNotEqual(code, 0, bad)
        self.assertEqual(list(self.empty.iterdir()), [])

    def test_a_rice_with_no_pair_still_installs(self):
        (self.noir / "README.md").write_text("# x\n\n## Palette\n")
        git("commit", "-qam", "y", cwd=self.noir)
        self.assertEqual(self.main("get", "noir")[0], 0)
        self.assertEqual([p.name for p in self.empty.iterdir()], ["cosmic-noir-theme"])

    def test_any_case_or_spaced_name_is_accepted(self):
        self.assertEqual(self.main("get", "Noir")[0], 0)


class Installer(unittest.TestCase):
    """Runs the real install.sh in a throwaway HOME. Network commands are stubs."""

    def setUp(self):
        import tempfile
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.good = b"\x7fELF applet"
        self.sum = hashlib.sha256(self.good).hexdigest()
        self.binary = self.root / "binary"
        self.binary.write_bytes(self.good)
        self.stub("curl", f'''out=""
while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;; esac; shift; done
case "$out" in
  *.sha256) echo "${{FAKE_SUM:-{self.sum}}}  cosmic-rice-applet" > "$out";;
  *) [ -n "$NO_RELEASE" ] && exit 22; cp "{self.binary}" "$out";;
esac
''')
        self.stub("uname", 'echo "${FAKE_ARCH:-x86_64}"\n')
        self.stub("git", f'''[ "$1" = clone ] || exit 0
target=""; for a in "$@"; do target="$a"; done
cp -r "{ROOT}" "$target"
''')

    def stub(self, name, body):
        f = self.bin / name
        f.write_text("#!/bin/sh\n" + body)
        f.chmod(f.stat().st_mode | stat.S_IXUSR)

    def run_it(self, **env):
        full = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin", "TMPDIR": str(self.root), **env}
        return subprocess.run(["bash", str(ROOT / "install.sh")], env=full, capture_output=True, text=True)

    def test_installs_the_cli_and_the_applet(self):
        done = self.run_it()
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        cli = self.home / ".local/bin/cosmic-rice"
        self.assertTrue(cli.is_symlink())
        self.assertTrue(cli.resolve().name == "cosmic_rice.py")
        applet = self.home / ".local/bin/cosmic-rice-applet"
        self.assertEqual(applet.read_bytes(), self.good)
        self.assertTrue(os.access(applet, os.X_OK))
        entry = self.home / ".local/share/applications/io.github.atraxsrc.CosmicRiceApplet.desktop"
        self.assertIn(f"Exec={applet}", entry.read_text())
        self.assertIn("X-CosmicApplet=true", entry.read_text())

    def test_a_wrong_checksum_installs_no_binary(self):
        done = self.run_it(FAKE_SUM="0" * 64)
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse((self.home / ".local/bin/cosmic-rice-applet").exists())

    def test_another_architecture_still_gets_the_cli(self):
        done = self.run_it(FAKE_ARCH="aarch64")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.home / ".local/bin/cosmic-rice").is_symlink())
        self.assertFalse((self.home / ".local/bin/cosmic-rice-applet").exists())
        self.assertIn("applet/install.sh", done.stdout)

    def test_no_release_yet_still_gets_the_cli(self):
        done = self.run_it(NO_RELEASE="1")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((self.home / ".local/bin/cosmic-rice").is_symlink())
        self.assertIn("applet/install.sh", done.stdout)

    def test_an_existing_command_elsewhere_is_left_alone(self):
        mine = self.root / "dev.py"
        mine.touch()
        (self.home / ".local/bin").mkdir(parents=True)
        (self.home / ".local/bin/cosmic-rice").symlink_to(mine)
        done = self.run_it()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(os.readlink(self.home / ".local/bin/cosmic-rice"), str(mine))

    def test_running_twice_updates_in_place(self):
        self.run_it()
        done = self.run_it()
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_missing_tool_is_named(self):
        import shutil
        lean = self.root / "lean"
        lean.mkdir()
        for tool in ("bash", "dirname", "mkdir"):
            (lean / tool).symlink_to(shutil.which(tool))
        done = subprocess.run(["bash", str(ROOT / "install.sh")], capture_output=True, text=True,
                              env={"HOME": str(self.home), "PATH": str(lean)})
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("git", done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
