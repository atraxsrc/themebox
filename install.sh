#!/usr/bin/env bash
# Install themebox and its panel applet for this user. No sudo. Run it again
# to update.
#
#   curl -fsSL https://raw.githubusercontent.com/atraxsrc/themebox/master/install.sh | bash
set -euo pipefail

REPO=https://github.com/atraxsrc/themebox
BASE="$HOME/.local/share/themebox"   # rices are cloned next to the app, so it finds them
APP="$BASE/themebox"
BIN="$HOME/.local/bin"
ENTRY="$HOME/.local/share/applications/io.github.atraxsrc.ThemeboxApplet.desktop"

for tool in git curl python3 sha256sum; do
    command -v "$tool" >/dev/null || { echo "themebox needs $tool, install it first"; exit 1; }
done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "themebox needs Python 3.11+"; exit 1; }

mkdir -p "$BASE" "$BIN" "$(dirname "$ENTRY")"
if [ -d "$APP/.git" ]; then
    git -C "$APP" pull --quiet --ff-only
else
    git clone --quiet --depth 1 "$REPO" "$APP"
fi

link="$BIN/themebox"
if [ ! -e "$link" ] && [ ! -L "$link" ] || [ "$(readlink -f "$link")" = "$APP/themebox.py" ]; then
    ln -sfn "$APP/themebox.py" "$link"
    echo "Installed themebox"
else
    echo "Left $link alone: it is not this install"
fi

applet_from_source() {
    echo "$1 To build the applet instead: $APP/applet/install.sh (needs Rust)"
}

install_applet() {
    local tmp url=$REPO/releases/latest/download/themebox-applet-x86_64
    if [ "$(uname -m)" != x86_64 ]; then
        applet_from_source "The prebuilt applet is x86_64 only."
        return 0
    fi
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' RETURN
    if ! curl -fsSL -o "$tmp/themebox-applet" "$url" \
        || ! curl -fsSL -o "$tmp/themebox-applet.sha256" "$url.sha256"; then
        applet_from_source "No prebuilt applet could be downloaded."
        return 0
    fi
    if ! (cd "$tmp" && sha256sum --check --status themebox-applet.sha256); then
        echo "The applet download failed its checksum, so it was not installed"
        return 1
    fi
    install -m 755 "$tmp/themebox-applet" "$BIN/themebox-applet"
    # the panel's PATH often leaves out ~/.local/bin, so name the binary in full
    sed "s|^Exec=.*|Exec=$BIN/themebox-applet|" "$APP/applet/data/themebox-applet.desktop" > "$ENTRY"
    echo "Installed the applet: add Themebox in Settings -> Desktop -> Panel -> Configure panel applets"
}
install_applet

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "Add $BIN to your PATH to run themebox" ;;
esac
echo "Next: themebox get <slug>, then themebox switch <slug>. Rices: https://atraxsrc.github.io/cosmic-rices/"
