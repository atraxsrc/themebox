#!/usr/bin/env python3
"""Write icon-palettes.toml: the colours of every icon pack, for the Icons tab.

A pack's colours live in cosmic-icon-themes, and a rice only downloads a pack when
asked, so themebox keeps this table. Run it again after changing the packs:

  tools/icon_palettes.py [path to cosmic-icon-themes, default beside this repo]
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
ROLES = (("Folder", "front"), ("Folder back", "back"), ("Symbol", "symbol"), ("Accent", "accent"),
         ("Trash", "trash_top"), ("Trash shade", "trash_bottom"))


def packs(source: Path) -> dict[str, dict[str, str]]:
    """Each pack's name and its colours by role."""
    sys.path.insert(0, str(source))
    from cosmic_icons.build import pack_name
    from cosmic_icons.palettes import THEMES
    from cosmic_icons.recolor import resolve
    table = {}
    for theme, spec in THEMES.items():
        for variant in spec["variants"]:
            colours = resolve(spec, variant)
            table[pack_name(theme, variant)] = {role: colours[key] for role, key in ROLES}
    return table


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parent / "cosmic-icon-themes"
    lines = ["# Made by tools/icon_palettes.py from cosmic-icon-themes. Do not edit by hand.\n"]
    for pack, colours in sorted(packs(source).items()):
        lines.append(f"\n[{pack}]\n")
        lines += [f'"{role}" = "{code}"\n' for role, code in colours.items()]
    (HERE / "icon-palettes.toml").write_text("".join(lines))


if __name__ == "__main__":
    main()
