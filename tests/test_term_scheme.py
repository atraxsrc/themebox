"""A rice's terminal scheme lands in COSMIC Terminal's own list, or the name in
syntax_theme_light finds nothing: open tabs keep the last rice's colours."""
import contextlib
import io
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import themebox as cr  # noqa: E402
from test_flip import FlipBase  # noqa: E402

# keys are bare numbers: the same shape as a real color_schemes_light
STORED = '''{
    8: (
        name: "White Gold",
        foreground: "#111111",
    ),
    11: (
        name: "Tokyo Day",
        foreground: "#222222",
    ),
}'''


class SchemeBase(FlipBase):
    def schemes(self, mode="light"):
        return self.conf / f"cosmic/com.system76.CosmicTerm/v1/color_schemes_{mode}"

    def store(self, text, mode="light"):
        self.schemes(mode).parent.mkdir(parents=True, exist_ok=True)
        self.schemes(mode).write_text(text)

    def full_scheme(self, repo, name):
        (repo / f"cosmic-term/{name}-term.ron").write_text(
            f'(\n    name: "{name}",\n    foreground: "#1A1B1B",\n    normal: (\n        red: "#B03316",\n    ),\n)\n')


class Adding(SchemeBase):
    def test_first_scheme_starts_at_zero(self):
        self.switch("dossier", steps=False)
        self.assertRegex(self.schemes().read_text(), r'^\{\n    0: \(\n        name: "Dossier",\n')

    def test_goes_in_the_list_for_the_rice_mode(self):
        self.switch("dossier", steps=False)
        self.assertIn("Noir", self.schemes("dark").read_text())
        self.assertNotIn("Noir", self.schemes("light").read_text())

    def test_takes_the_id_after_the_highest(self):
        self.store(STORED)
        self.switch("dossier", steps=False)
        self.assertIn('    12: (\n        name: "Dossier",\n', self.schemes().read_text())

    def test_keeps_what_was_stored(self):
        self.store(STORED)
        self.switch("dossier", steps=False)
        self.assertTrue(self.schemes().read_text().startswith(STORED[:-1]))

    def test_every_key_is_a_bare_number(self):
        self.store(STORED)
        self.switch("dossier", steps=False)
        self.assertEqual(re.findall(r"^    (\S+): \($", self.schemes().read_text(), re.M), ["8", "11", "12"])

    def test_the_list_stays_one_map(self):
        self.store(STORED)
        self.switch("dossier", steps=False)
        self.assertTrue(self.schemes().read_text().endswith("    ),\n}\n"))

    def test_an_empty_list_works(self):
        self.store("{}")
        self.switch("dossier", steps=False)
        self.assertIn('    0: (\n        name: "Dossier",\n', self.schemes().read_text())

    def test_a_list_with_no_final_comma_works(self):
        self.store('{\n    0: (\n        name: "White Gold",\n    )\n}')
        self.switch("dossier", steps=False)
        self.assertIn('    ),\n    1: (\n', self.schemes().read_text())

    def test_nested_colours_stay_nested(self):
        self.full_scheme(self.dossier, "Dossier")
        self.switch("dossier", steps=False)
        self.assertIn('        normal: (\n            red: "#B03316",\n        ),\n', self.schemes().read_text())

    def test_replaced_list_is_backed_up(self):
        self.store(STORED)
        self.switch("dossier", steps=False)
        self.assertEqual(self.schemes().with_name("color_schemes_light.bak").read_text(), STORED)


class Leaving(SchemeBase):
    def test_a_scheme_already_there_changes_nothing(self):
        self.store('{\n    0: (\n        name: "Dossier",\n    ),\n}')
        self.switch("dossier", steps=False)
        self.assertEqual(self.schemes().read_text(), '{\n    0: (\n        name: "Dossier",\n    ),\n}')
        self.assertFalse(self.schemes().with_name("color_schemes_light.bak").exists())

    def test_a_list_it_cannot_read_is_left_alone(self):
        self.store("not a list")
        ok, out = self.switch("dossier", steps=False)
        self.assertTrue(ok)
        self.assertEqual(self.schemes().read_text(), "not a list")

    def test_a_rice_with_no_scheme_file_adds_nothing(self):
        (self.dossier / "cosmic-term/Dossier-term.ron").unlink()
        self.switch("dossier", steps=False)
        self.assertFalse(self.schemes().exists())

    def test_a_scheme_with_no_name_adds_nothing(self):
        (self.dossier / "cosmic-term/Dossier-term.ron").write_text("(\n)\n")
        self.assertTrue(self.switch("dossier", steps=False)[0])
        self.assertFalse(self.schemes().exists())


class HandSteps(SchemeBase):
    def test_flip_adds_the_scheme(self):
        self.flip()
        self.assertIn("Dossier", self.schemes().read_text())

    def test_flip_no_longer_asks_for_the_import(self):
        self.assertNotIn("Color schemes", self.flip()[1])

    def test_flip_asks_when_the_list_could_not_be_changed(self):
        self.store("not a list")
        self.assertIn("Color schemes", self.flip()[1])

    def test_switch_no_longer_asks_for_the_import(self):
        self.assertNotIn("Color schemes", self.switch("dossier")[1])

    def test_switch_asks_when_the_list_could_not_be_changed(self):
        self.store("not a list")
        self.assertIn("Color schemes", self.switch("dossier")[1])


class PairFollow(SchemeBase):
    def test_following_the_toggle_adds_the_scheme(self):
        cr.mode_file().write_text("false\n")
        with contextlib.redirect_stdout(io.StringIO()):
            cr.follow(self.rices())
        self.assertIn("Dossier", self.schemes().read_text())


if __name__ == "__main__":
    unittest.main()
