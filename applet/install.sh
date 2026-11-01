#!/usr/bin/env bash
# Build the panel applet and install it for this user. Then add it once in
# Settings -> Desktop -> Panel -> Configure panel applets.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
cargo build --release
mkdir -p ~/.local/bin ~/.local/share/applications
install -m 755 target/release/cosmic-rice-applet ~/.local/bin/
# the panel's PATH often leaves out ~/.local/bin, so name the binary in full
sed "s|^Exec=.*|Exec=$HOME/.local/bin/cosmic-rice-applet|" data/cosmic-rice-applet.desktop \
    > ~/.local/share/applications/io.github.atraxsrc.CosmicRiceApplet.desktop
echo "Installed. Add Rice Flip in Settings -> Desktop -> Panel -> Configure panel applets."
