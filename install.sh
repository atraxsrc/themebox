#!/usr/bin/env bash
# Install cosmic-rice and its panel applet for this user. No sudo. Run it again
# to update.
#
#   curl -fsSL https://raw.githubusercontent.com/atraxsrc/cosmic-rice/master/install.sh | bash
set -euo pipefail

REPO=https://github.com/atraxsrc/cosmic-rice
BASE="$HOME/.local/share/cosmic-rice"   # rices are cloned next to the app, so it finds them
APP="$BASE/cosmic-rice"
BIN="$HOME/.local/bin"
ENTRY="$HOME/.local/share/applications/io.github.atraxsrc.CosmicRiceApplet.desktop"

for tool in git curl python3 sha256sum; do
    command -v "$tool" >/dev/null || { echo "cosmic-rice needs $tool, install it first"; exit 1; }
done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "cosmic-rice needs Python 3.10+"; exit 1; }

mkdir -p "$BASE" "$BIN" "$(dirname "$ENTRY")"
if [ -d "$APP/.git" ]; then
    git -C "$APP" pull --quiet --ff-only
else
    git clone --quiet --depth 1 "$REPO" "$APP"
fi

link="$BIN/cosmic-rice"
if [ ! -e "$link" ] && [ ! -L "$link" ] || [ "$(readlink -f "$link")" = "$APP/cosmic_rice.py" ]; then
    ln -sfn "$APP/cosmic_rice.py" "$link"
    echo "Installed cosmic-rice"
else
    echo "Left $link alone: it is not this install"
fi

applet_from_source() {
    echo "$1 To build the applet instead: $APP/applet/install.sh (needs Rust)"
}

install_applet() {
    local tmp url=$REPO/releases/latest/download/cosmic-rice-applet-x86_64
    if [ "$(uname -m)" != x86_64 ]; then
        applet_from_source "The prebuilt applet is x86_64 only."
        return 0
    fi
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' RETURN
    if ! curl -fsSL -o "$tmp/cosmic-rice-applet" "$url" \
        || ! curl -fsSL -o "$tmp/cosmic-rice-applet.sha256" "$url.sha256"; then
        applet_from_source "No prebuilt applet could be downloaded."
        return 0
    fi
    if ! (cd "$tmp" && sha256sum --check --status cosmic-rice-applet.sha256); then
        echo "The applet download failed its checksum, so it was not installed"
        return 1
    fi
    install -m 755 "$tmp/cosmic-rice-applet" "$BIN/cosmic-rice-applet"
    # the panel's PATH often leaves out ~/.local/bin, so name the binary in full
    sed "s|^Exec=.*|Exec=$BIN/cosmic-rice-applet|" "$APP/applet/data/cosmic-rice-applet.desktop" > "$ENTRY"
    echo "Installed the applet: add Rice Flip in Settings -> Desktop -> Panel -> Configure panel applets"
}
install_applet

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "Add $BIN to your PATH to run cosmic-rice" ;;
esac
echo "Next: cosmic-rice get <slug>, then cosmic-rice switch <slug>. Rices: https://atraxsrc.github.io/cosmic-rices/"
