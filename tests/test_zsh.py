"""Live zsh reload, with a real zsh in a pty. Never signals anything it did not start."""
import os
import pty
import select
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cosmic_rice as cr  # noqa: E402
from test_flip import FlipBase  # noqa: E402

SNIPPET = Path(cr.__file__).resolve().parent / "zsh/reload.zsh"


class Shell(FlipBase):
    def setUp(self):
        super().setUp()
        (self.noir / "zsh/noir.zsh").write_text("export RICE=noir\n")
        (self.dossier / "zsh/dossier.zsh").write_text("export RICE=dossier\n")
        self.kids = []
        self.addCleanup(self.stop_all)

    def stop_all(self):
        for pid, fd in self.kids:
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass
            os.close(fd)

    def spawn(self, registered=True):
        rc = self.home / ".zshrc"
        rc.write_text(f'source "{SNIPPET}"\n' if registered else "\n")
        pid, fd = pty.fork()
        if pid == 0:
            os.execvpe("zsh", ["zsh", "-i"], {**os.environ, "ZDOTDIR": str(self.home)})
        self.kids.append((pid, fd))
        self.drain(fd, 1.5)
        return pid, fd

    @staticmethod
    def drain(fd, seconds):
        end, out = time.time() + seconds, b""
        while time.time() < end:
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    out += os.read(fd, 65536)
                except OSError:
                    break
        return out.decode(errors="replace")

    def alive(self, pid):
        return os.waitpid(pid, os.WNOHANG) == (0, 0)

    def test_registered_shell_reloads_keeping_a_half_typed_line(self):
        pid, fd = self.spawn()
        os.write(fd, b"echo now=$RICE")
        self.drain(fd, 0.3)
        (self.home / "update_system.sh").unlink()
        (self.home / "update_system.sh").symlink_to(self.dossier / "scripts/update_system.sh")
        cr.reload_zsh()
        self.drain(fd, 0.5)
        os.write(fd, b"\n")
        out = self.drain(fd, 0.7)
        self.assertIn("now=dossier", out)
        self.assertTrue(self.alive(pid))

    def test_relative_link_is_not_resolved_against_the_shells_folder(self):
        trap = self.root / "elsewhere"
        (trap / "a/zsh").mkdir(parents=True)
        (trap / "a/zsh/evil.zsh").write_text("export RICE=evil\n")
        pid, fd = self.spawn()
        os.write(fd, f"cd {trap}\n".encode())
        self.drain(fd, 0.4)
        link = self.home / "update_system.sh"
        link.unlink()
        link.symlink_to("a/b/x")  # dangling from HOME, but real from the trap folder
        cr.reload_zsh()
        self.drain(fd, 0.5)
        os.write(fd, b"echo now=$RICE\n")
        self.assertNotIn("now=evil", self.drain(fd, 0.7))

    def test_dangling_link_sources_nothing(self):
        (self.root / "zsh").mkdir()
        (self.root / "zsh/evil.zsh").write_text("export RICE=evil\n")  # the parent of HOME
        pid, fd = self.spawn()
        link = self.home / "update_system.sh"
        link.unlink()
        link.symlink_to("x")
        cr.reload_zsh()
        self.drain(fd, 0.5)
        os.write(fd, b"echo now=$RICE\n")
        self.assertNotIn("now=evil", self.drain(fd, 0.7))

    def test_unregistered_shell_gets_no_signal_and_lives(self):
        pid, fd = self.spawn(registered=False)
        cr.reload_zsh()
        self.drain(fd, 0.5)
        self.assertTrue(self.alive(pid))

    def test_pid_of_a_non_zsh_is_not_signalled_and_is_removed(self):
        sleeper = subprocess.Popen(["sleep", "30"])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        d = self.run_dir / "cosmic-rice/zsh"
        d.mkdir(parents=True)
        (d / str(sleeper.pid)).touch()
        (d / "999999").touch()
        (d / "notapid").touch()
        (self.home / ".zshrc").write_text(f'source "{SNIPPET}"\n')
        cr.reload_zsh()
        time.sleep(0.2)
        self.assertIsNone(sleeper.poll())
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["notapid"])

    def test_install_shell_adds_one_line_once_with_bak(self):
        rc = self.home / ".zshrc"
        rc.write_text("export A=1\n")
        self.assertTrue(cr.install_shell())
        self.assertFalse(cr.install_shell())
        self.assertEqual(rc.read_text().count("reload.zsh"), 1)
        self.assertTrue(rc.read_text().startswith("export A=1\n"))
        self.assertIn("export A=1", (self.home / ".zshrc.bak").read_text())

    def test_report_says_run_install_shell_when_line_is_missing(self):
        (self.home / ".zshrc").write_text("\n")
        self.assertTrue(any("install-shell" in m for m in cr.reload_zsh()))
        cr.install_shell()
        self.assertEqual(cr.reload_zsh(), [])

    def test_flip_reloads_registered_shells(self):
        (self.home / ".zshrc").write_text(f'source "{SNIPPET}"\n')
        self.flip()  # no shells registered: must not raise
        self.assertTrue((self.home / "update_system.sh").is_symlink())


if __name__ == "__main__":
    unittest.main()
