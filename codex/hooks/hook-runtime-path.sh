#!/bin/bash -p

# Establish a safe baseline before resolving any hook dependency by basename.
PATH="/usr/bin:/bin:/usr/sbin:/sbin"

dots_hook_path_is_protected() {
  local current="$1"
  local owner=""
  local platform=""

  platform="$(/usr/bin/uname -s)" || return 1
  while true; do
    [[ -d "$current" && ! -w "$current" ]] || return 1
    case "$platform" in
      Darwin) owner="$(/usr/bin/stat -f '%u' "$current" 2>/dev/null)" || return 1 ;;
      Linux) owner="$(/usr/bin/stat -c '%u' "$current" 2>/dev/null)" || return 1 ;;
      *) return 1 ;;
    esac
    [[ "$owner" == "0" ]] || return 1
    [[ "$current" == "/" ]] && return 0
    current="${current%/*}"
    [[ -n "$current" ]] || current="/"
  done
}

dots_hook_add_protected_path() {
  local candidate="$1"
  local resolved=""

  [[ -d "$candidate" ]] || return 0
  dots_hook_path_is_protected "$candidate" || return 0
  resolved="$(cd -P "$candidate" 2>/dev/null && pwd -P)" || return 0
  dots_hook_path_is_protected "$resolved" || return 0
  PATH="$candidate:$PATH"
}

# Preserve supported package-manager locations only when lower-trust code
# cannot replace their contents. The order matches the historical hook PATH.
dots_hook_add_protected_path "/usr/local/bin"
dots_hook_add_protected_path "/opt/homebrew/bin"
export PATH

unset -f dots_hook_add_protected_path dots_hook_path_is_protected
