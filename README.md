# themebox

One command to list your [COSMIC rices](https://atraxsrc.github.io/cosmic-rices/), switch between them,
and have the matching light or dark half follow COSMIC's toggle.

![themebox list showing every rice, its mode and its pair, with Noir marked active](assets/list.png)

Flip the desktop to light and Noir becomes its light half, Dossier. Flip back and Noir returns:

![The Noir desktop beside the Dossier desktop, the dark and light halves of one pair](assets/pair.jpg)

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/atraxsrc/themebox/master/install.sh | bash
themebox get noir            # download a rice and its other half
themebox switch noir         # make it active
```

Then add Themebox in Settings → Desktop → Panel → Configure panel applets. It needs git, curl and
Python 3.10+. Browse the rices in the [gallery](https://atraxsrc.github.io/cosmic-rices/); the name to use
is the part of the repo name between `cosmic-` and `-theme`.

Everything goes in `~/.local/share/themebox`, plus two files in `~/.local/bin` and one in
`~/.local/share/applications`. Run the same command again to update. The applet is prebuilt for x86_64; on
anything else the installer gives you the CLI, and `applet/install.sh` builds the applet from source.

The applet is not in the COSMIC Store: Store apps run in a sandbox, and this one has to change your config
files and reach your open shells.

To work on it, clone this repo next to the `cosmic-*-theme` repos and link `themebox.py` into
`~/.local/bin` as `themebox`.

## Use

```bash
themebox get noir            # download a rice and its other half
themebox list                # every rice, * marks the active one
themebox switch noir         # make a rice active, --keep-icons leaves the icon theme alone
themebox pair                # match the rice to COSMIC's light/dark setting, once
themebox pair --watch        # keep matching it
themebox flip                # move to the other half and change everything live
themebox choose noir k3day   # flip between these two instead of a rice's own pair
themebox choose --reset      # back to each rice's own pair
themebox install-shell       # once: let flip reload open zsh shells
```

`flip` moves to the other half of the active rice. It applies the configs, imports the COSMIC theme,
sets the matching wallpaper, recolours running Neovims and reloads registered zsh shells. Then it sends
a notification with whatever is left, such as the Firefox add-on. It replaces COSMIC's stored theme for
that mode, so changes made in Settings are lost on the next flip.

`install-shell` adds one line to `~/.zshrc`. Terminals opened before that line existed are not reloaded.
Nothing is closed either way.

`switch` does what a rice's `scripts/switch.sh` does and backs up what it replaces (`*.bak`). If one
tool fails the others still run, the failures are listed at the end and the exit code is 1. It finishes
with the steps COSMIC only allows by hand, such as importing the theme.

`pair` needs both halves imported once in Settings → Desktop → Appearance, one in the Dark tab and one
in the Light tab. The active rice is whichever repo `~/update_system.sh` links into, so run `switch`
once first.

To follow the toggle from login, save this as `~/.config/systemd/user/themebox-pair.service`, then
run `systemctl --user enable --now themebox-pair`:

```ini
[Unit]
Description=Follow the COSMIC light/dark toggle with the matching rice

[Service]
ExecStart=%h/.local/bin/themebox pair --watch
Restart=on-failure

[Install]
WantedBy=default.target
```

## Panel applet

`applet/` is a one-button panel applet that runs `themebox flip`. The icon shows the current mode, and
the logic stays in the CLI. It needs Rust and the libcosmic build dependencies.

```bash
./applet/install.sh
```

Then add Themebox in Settings → Desktop → Panel → Configure panel applets.

## How it reads the rices

Each rice's settings come from the block at the top of its `scripts/switch.sh`, and its pair from the
link in its README. Set `THEMEBOX_REPOS` if the repos live somewhere else.

## Tests

```bash
python3 -m unittest discover -s tests
```

`tests/test_parity.py` runs every rice through both its `switch.sh` and this CLI in throwaway home
folders and compares every file they leave behind.

## License

MIT
