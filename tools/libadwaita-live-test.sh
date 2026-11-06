#!/usr/bin/env bash
# Live test of the built-in libadwaita and libadwaita-vars templates (amo-aqp.21, amo-j24.2) in
# real GTK4 apps.
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

Render amontillado's built-in libadwaita and libadwaita-vars templates from a palette and open
GTK4 apps on them, one scenario at a time: close the app's window to go on to the next.

Scenarios (default: all of them, in this order):
  dark      adwaita-1-demo, dark variant, dark colour scheme (the intended setup)
  light     adwaita-1-demo, light variant, light colour scheme
  mismatch  adwaita-1-demo, dark variant, default (light) colour scheme: shows why the desktop's
            color-scheme must match the variant (libadwaita derives the standalone accent,
            success, warning and error text colours from the scheme, not from the file)
  editor    gnome-text-editor, dark variant, dark colour scheme: a real app
  vars      adwaita-1-demo on libadwaita-vars, dark variant, default (light) colour scheme: the
            mismatch setup, which the file's pinned standalone colours should fix, and GNOME's
            palette remapped (Animations, Tab View)

Options:
  -p, --palette FILE  A palette file (`amo palette` output) with both variants. Default: gruvbox
                      hard, from tools/assets/gruvbox-{dark,light}-hard.yaml.
  -r, --render-only   Render, print the files and the checklist, launch nothing.
  -s, --screenshot DIR
                      Instead of waiting for you, open each scenario's pages and capture them
                      into DIR (PNG, plus a contact sheet per scenario with ImageMagick), then
                      close the app (tools/libadwaita_screenshots.py). Specific to MH's setup:
                      Hyprland only; needs grim, wtype, an AT-SPI bus and the system python3
                      with PyGObject's Atspi. It types keys into the focused window, checking
                      before each one that it is the app's: do not switch windows while it runs.
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
screenshots=
render_only=false
keep=false
scenarios=()
while (($#)); do
    case $1 in
        -p | --palette)
            palette=$(realpath "${2:?--palette needs a file}")
            shift 2
            ;;
        -s | --screenshot)
            mkdir -p "${2:?--screenshot needs a directory}"
            screenshots=$(realpath "$2")
            shift 2
            ;;
        -r | --render-only) render_only=true && shift ;;
        -k | --keep) keep=true && shift ;;
        -h | --help) usage && exit 0 ;;
        dark | light | mismatch | editor | vars) scenarios+=("$1") && shift ;;
        all) scenarios+=(dark light mismatch editor vars) && shift ;;
        *) echo "libadwaita-live-test: unknown argument: $1 (see --help)" >&2 && exit 2 ;;
    esac
done
((${#scenarios[@]})) || scenarios=(dark light mismatch editor vars)

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
printf 'theme:\n  apps:\n    libadwaita: {}\n    gtk4: {template: libadwaita-vars}\n' \
    >"$work/amo-config/amontillado/config.yaml"
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
mkdir -p "$work/dark-vars/gtk-4.0"
cp "$work/amo-cache/theme/dark/libadwaita-vars.css" "$work/dark-vars/gtk-4.0/gtk.css"
echo "dark (libadwaita-vars): $work/dark-vars/gtk-4.0/gtk.css"

# A variable as rendered, for the checklist: variable VARIANT-DIR NAME (without the --).
variable() {
    sed -n "s/^  --$2: \(#[0-9a-f]*\);$/\1/p" "$work/$1/gtk-4.0/gtk.css"
}

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
        vars)
            echo "== vars: adwaita-1-demo on libadwaita-vars, dark variant, default (light) scheme"
            echo "  - Unlike 'mismatch': accent ($(variable dark-vars accent-color)), success, warning and error"
            echo "    text on the Style Classes demo readable on the dark window, as in 'dark'."
            echo "  - Toggle Groups page: the active segment clearly lighter than its track, on the"
            echo "    window and on the cards alike, with $(variable dark-vars active-toggle-fg-color) text."
            echo "  - Animations page: the ball's gradient runs from green-2 $(variable dark-vars green-2) to"
            echo "    green-5 $(variable dark-vars green-5), not GNOME's #57e389 to #26a269."
            echo "  - Tab View page, Run the Demo: tab colours from the palette (blue-3"
            echo "    $(variable dark-vars blue-3), red-3 $(variable dark-vars red-3), ...), not GNOME's; the tab"
            echo "    overview background $(variable dark-vars overview-bg-color)."
            echo "  - Expected still light-scheme: anything drawn from the scheme rather than the"
            echo "    stylesheet (icons and images an app picks per scheme)."
            ;;
    esac
}

launch() {
    local scenario=$1 variant=$2 scheme=$3 app=$4
    shift 4
    if ! command -v "$app" >/dev/null; then
        echo "  skipped: $app is not installed" >&2
        return
    fi
    # By argv[0], not the process name: Linux truncates that to 15 characters
    # (gnome-text-editor is 17), so `pgrep -x` never matches it.
    if pgrep -f "^(\S*/)?$app( |$)" >/dev/null; then
        echo "  skipped: $app is already running; close it and run this scenario again" >&2
        return
    fi
    if [[ -z $screenshots ]]; then
        echo "  (close the window to go on)"
        XDG_CONFIG_HOME=$work/$variant ADW_DEBUG_COLOR_SCHEME=$scheme "$app" >/dev/null 2>&1 || true
        return
    fi
    echo "  capturing into $screenshots (do not switch windows)"
    XDG_CONFIG_HOME=$work/$variant ADW_DEBUG_COLOR_SCHEME=$scheme "$app" >/dev/null 2>&1 &
    local pid=$! status=0
    # The system python3: PyGObject (Atspi) is not in the project's venv.
    /usr/bin/env python3 -I "$repo/tools/libadwaita_screenshots.py" --app "$app" \
        --prefix "$scenario" "$screenshots" "$@" || status=$?
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    return "$status"
}

for scenario in "${scenarios[@]}"; do
    echo
    describe "$scenario"
    $render_only && continue
    case $scenario in
        dark) launch dark dark prefer-dark adwaita-1-demo ;;
        light) launch light light prefer-light adwaita-1-demo ;;
        mismatch) launch mismatch dark default adwaita-1-demo "Style Classes+Run the Demo" ;;
        editor) launch editor dark prefer-dark gnome-text-editor ;;
        vars) launch vars dark-vars default adwaita-1-demo \
            "Toggle Groups" "Animations" "Style Classes+Run the Demo" ;;
    esac
done
