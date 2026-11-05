#!/usr/bin/env bash
# Live test of the built-in libadwaita template (amo-aqp.21) in real GTK4 apps.
#
# Renders the template through amontillado itself (amo palette, amo theme apply) from the working
# tree, so it always tests the current template, then launches GTK4 apps on the result. Nothing
# outside a temporary directory is touched: amontillado gets its own XDG_CONFIG_HOME and
# XDG_CACHE_HOME, each app gets an XDG_CONFIG_HOME holding only gtk-4.0/gtk.css, and the dark or
# light preference comes from libadwaita's ADW_DEBUG_COLOR_SCHEME instead of gsettings.
#
# Run `tools/libadwaita-live-test.sh --help` for usage and what to look at.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
assets=$repo/tools/assets

usage() {
    cat <<'EOF'
Usage: tools/libadwaita-live-test.sh [-p PALETTE] [-r] [-k] [SCENARIO...]

Render amontillado's built-in libadwaita template from a palette and open GTK4 apps on it, one
scenario at a time: close the app's window to go on to the next.

Scenarios (default: all of them, in this order):
  dark      adwaita-1-demo, dark variant, dark colour scheme (the intended setup)
  light     adwaita-1-demo, light variant, light colour scheme
  mismatch  adwaita-1-demo, dark variant, default (light) colour scheme: shows why the desktop's
            color-scheme must match the variant (libadwaita derives the standalone accent,
            success, warning and error text colours from the scheme, not from the file)
  editor    gnome-text-editor, dark variant, dark colour scheme: a real app

Options:
  -p, --palette FILE  A palette file (`amo palette` output) with both variants. Default: gruvbox
                      hard, from tools/assets/gruvbox-{dark,light}-hard.yaml.
  -r, --render-only   Render, print the files and the checklist, launch nothing.
  -k, --keep          Keep the temporary directory (printed at the start).
  -h, --help          Show this help.

Needs: uv (runs amontillado from this checkout), adwaita-1-demo (Fedora: libadwaita-demo) and
gnome-text-editor for the scenarios that use them. Close any running copy of an app first:
both are single-instance, so a second launch only raises the old window with the old theme.

What to look at is printed before each scenario. Report what you saw (screenshots welcome) on
the bead.
EOF
}

palette=
render_only=false
keep=false
scenarios=()
while (($#)); do
    case $1 in
        -p | --palette)
            palette=$(realpath "${2:?--palette needs a file}")
            shift 2
            ;;
        -r | --render-only) render_only=true && shift ;;
        -k | --keep) keep=true && shift ;;
        -h | --help) usage && exit 0 ;;
        dark | light | mismatch | editor) scenarios+=("$1") && shift ;;
        all) scenarios+=(dark light mismatch editor) && shift ;;
        *) echo "libadwaita-live-test: unknown argument: $1 (see --help)" >&2 && exit 2 ;;
    esac
done
((${#scenarios[@]})) || scenarios=(dark light mismatch editor)

work=$(mktemp -d "${TMPDIR:-/tmp}/amo-libadwaita.XXXXXX")
if $keep; then
    echo "work directory (kept): $work"
else
    trap 'rm -rf "$work"' EXIT
fi

amo() {
    (cd "$repo" && XDG_CONFIG_HOME=$work/amo-config XDG_CACHE_HOME=$work/amo-cache \
        uv run --quiet amo --loglevel WARNING "$@")
}

mkdir -p "$work/amo-config/amontillado"
printf 'theme:\n  apps:\n    libadwaita: {}\n' >"$work/amo-config/amontillado/config.yaml"
if [[ -z $palette ]]; then
    palette=$work/palette.yaml
    amo palette --from-scheme "$assets/gruvbox-dark-hard.yaml" \
        "$assets/gruvbox-light-hard.yaml" >"$palette"
fi
for variant in dark light; do
    amo theme apply --palette "$palette" --profile "$variant" --variant "$variant" --no-reload
    mkdir -p "$work/$variant/gtk-4.0"
    cp "$work/amo-cache/theme/$variant/libadwaita.css" "$work/$variant/gtk-4.0/gtk.css"
    echo "$variant: $work/$variant/gtk-4.0/gtk.css"
done

# A colour as rendered, for the checklist: colour VARIANT NAME.
colour() {
    sed -n "s/^@define-color $2 \(#[0-9a-f]*\);$/\1/p" "$work/$1/gtk-4.0/gtk.css"
}

checklist() {
    local variant=$1 step
    [[ $variant == dark ]] && step=lighter || step=darker
    cat <<EOF
  - Window: $(colour "$variant" window_bg_color), text $(colour "$variant" window_fg_color). Sidebar and
    header bar one step $step: $(colour "$variant" sidebar_bg_color).
  - Buttons page: "Suggested" buttons $(colour "$variant" accent_bg_color) with $(colour "$variant" accent_fg_color) labels;
    "Destructive" buttons $(colour "$variant" destructive_bg_color) with readable labels.
  - Styles / Labels page: accent, success, warning and error text readable on the window.
  - Banners, Toasts, Dialogs pages: dialog and popover backgrounds ($(colour "$variant" dialog_bg_color))
    visibly apart from the window; shadows not grey smears.
  - Tab overview: thumbnails and cards match the rest.
  - Anything in GNOME blue (#3584e4) is a colour the template does not reach.
EOF
}

describe() {
    case $1 in
        dark | light)
            echo "== $1: adwaita-1-demo, $1 variant, prefer-$1"
            checklist "$1"
            ;;
        mismatch)
            echo "== mismatch: adwaita-1-demo, dark variant, default (light) scheme"
            echo "  - Expected to look wrong: accent, success, warning and error *text* comes out"
            echo "    dark on the dark window, because libadwaita derives it for a light scheme."
            echo "    Backgrounds and buttons still follow the file."
            ;;
        editor)
            echo "== editor: gnome-text-editor, dark variant, prefer-dark"
            echo "  - Window chrome (header bar, sidebar, popovers) follows the file, as in 'dark'."
            echo "  - The text area keeps the GtkSourceView style Text Editor picks for a dark"
            echo "    scheme: not themed by this template, expected."
            ;;
    esac
}

launch() {
    local variant=$1 scheme=$2 app=$3
    if ! command -v "$app" >/dev/null; then
        echo "  skipped: $app is not installed" >&2
        return
    fi
    if pgrep -x "$app" >/dev/null; then
        echo "  skipped: $app is already running; close it and run this scenario again" >&2
        return
    fi
    echo "  (close the window to go on)"
    XDG_CONFIG_HOME=$work/$variant ADW_DEBUG_COLOR_SCHEME=$scheme "$app" >/dev/null 2>&1 || true
}

for scenario in "${scenarios[@]}"; do
    echo
    describe "$scenario"
    $render_only && continue
    case $scenario in
        dark) launch dark prefer-dark adwaita-1-demo ;;
        light) launch light prefer-light adwaita-1-demo ;;
        mismatch) launch dark default adwaita-1-demo ;;
        editor) launch dark prefer-dark gnome-text-editor ;;
    esac
done
