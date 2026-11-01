# Lets themebox flip recolour this shell while it is open. Added to ~/.zshrc
# by: themebox install-shell
[[ -o interactive && -n $XDG_RUNTIME_DIR ]] || return 0

# USR1 reloads the active rice's zsh file. The rice is whichever repo the
# updater link points into.
TRAPUSR1() {
    local link=~/update_system.sh repo file
    [[ -L $link && -e $link ]] || return 0
    repo=${${link:A}:h:h}   # :A resolves against the link, never the shell's folder
    for file in $repo/zsh/*.zsh(N); do
        source $file
    done
    zle && zle reset-prompt
    return 0
}

# Registers this shell, after the trap exists. USR1 kills a zsh with no trap, so
# flip signals only the shells listed here.
_themebox_shells=$XDG_RUNTIME_DIR/themebox/zsh
mkdir -p $_themebox_shells
: > $_themebox_shells/$$
_themebox_exit() { rm -f $_themebox_shells/$$ }
autoload -Uz add-zsh-hook
add-zsh-hook zshexit _themebox_exit
