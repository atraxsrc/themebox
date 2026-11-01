# Lets cosmic-rice flip recolour this shell while it is open. Added to ~/.zshrc
# by: cosmic-rice install-shell
[[ -o interactive && -n $XDG_RUNTIME_DIR ]] || return 0

# USR1 reloads the active rice's zsh file. The rice is whichever repo the
# updater link points into.
TRAPUSR1() {
    local link repo file
    link=$(readlink ~/update_system.sh) || return 0
    repo=${link:h:h}
    for file in $repo/zsh/*.zsh(N); do
        source $file
    done
    zle && zle reset-prompt
    return 0
}

# Registers this shell, after the trap exists. USR1 kills a zsh with no trap, so
# flip signals only the shells listed here.
_cosmic_rice_shells=$XDG_RUNTIME_DIR/cosmic-rice/zsh
mkdir -p $_cosmic_rice_shells
: > $_cosmic_rice_shells/$$
_cosmic_rice_exit() { rm -f $_cosmic_rice_shells/$$ }
autoload -Uz add-zsh-hook
add-zsh-hook zshexit _cosmic_rice_exit
