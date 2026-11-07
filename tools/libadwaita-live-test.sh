#!/usr/bin/env bash
# Live test of the built-in libadwaita and libadwaita-vars templates (amo-aqp.21, amo-j24.2) in
# real GTK4 apps.
#
# Renders the templates through amontillado itself (amo palette, amo theme apply) from the working
# tree, so it always tests the current templates, then launches GTK4 apps on the result. Nothing
# outside a temporary directory is touched: amontillado gets its own XDG_CONFIG_HOME and
# XDG_CACHE_HOME, each app gets an XDG_CONFIG_HOME holding only gtk-4.0/gtk.css, and the dark or
# light preference comes from libadwaita's ADW_DEBUG_COLOR_SCHEME instead of gsettings. Only
# --picture reads your own amontillado config (to find the library), and only to print a palette.
#
# Run `tools/libadwaita-live-test.sh --help` for usage and what to look at.
set -euo pipefail

repo=$(cd "$(dirname "$0")/.." && pwd)
assets=$repo/tools/assets

usage() {
    cat <<'EOF'
Usage: tools/libadwaita-live-test.sh [-p PALETTE | -S SCHEME [-S SCHEME] | -P PICTURE]
                                     [-r] [-s DIR [--hidden]] [-k] [SCENARIO...]

Render amontillado's built-in libadwaita and libadwaita-vars templates from a palette and open
GTK4 apps on them, one scenario at a time: close the app's window to go on to the next.

Scenarios (default: all of them, in this order):
  dark        adwaita-1-demo, dark variant, dark colour scheme (the intended setup)
  light       adwaita-1-demo, light variant, light colour scheme
  mismatch    adwaita-1-demo, dark variant, default (light) colour scheme: shows why the desktop's
              color-scheme must match the variant for the libadwaita template (libadwaita
              derives the standalone accent, success, warning and error text colours from the
              scheme, not from the file)
  editor      gnome-text-editor, dark variant, dark colour scheme: a real app
  vars-dark   adwaita-1-demo on libadwaita-vars, dark variant, light colour scheme
  vars-light  adwaita-1-demo on libadwaita-vars, light variant, dark colour scheme
              Each under the opposite scheme: libadwaita-vars pins what libadwaita would derive
              from the scheme, so these should look like 'dark' and 'light'. Also GNOME's
              palette remapped (Animations, Tab View).
  vars        both vars scenarios
A scenario whose variant the palette lacks (a single scheme has one) is skipped.

Palette (one of; default: gruvbox hard, from tools/assets/gruvbox-{dark,light}-hard.yaml):
  -p, --palette FILE  A palette file (`amo palette` output).
  -S, --scheme FILE   A tinted-theming scheme (base16 or base24 YAML). Give it twice for a dark
                      and a light scheme of one family, which make one palette with both
                      variants (amo palette --from-scheme). Contrast is adjusted as by default.
  -P, --picture PICTURE
                      A picture in your library (file, directory, name or id), through
                      `amo palette PICTURE` with your own config: the palette applying it would
                      give, both variants.

Options:
  -r, --render-only   Render, print the files and the checklist, launch nothing.
  -s, --screenshot DIR
                      Instead of waiting for you, open each scenario's pages and capture them
                      into DIR (PNG, plus a contact sheet per scenario with ImageMagick), then
                      close the app (tools/libadwaita_screenshots.py). Never takes keyboard
                      focus: work in another window meanwhile, but keep the workspace the run
                      started on visible (GTK does not update a window it is not drawing).
                      Specific to MH's setup: Hyprland 0.56+, grim 1.5+, an AT-SPI bus and the
                      system python3 with PyGObject's Atspi.
      --hidden        With --screenshot: run the apps on a headless output created for the run
                      and removed after, so nothing appears on screen. Fires Hyprland's
                      monitor.added/removed events, which your config may act on (see
                      tools/libadwaita_screenshots.py --help).
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
picture=
schemes=()
screenshots=
render_only=false
hidden=false
keep=false
scenarios=()
while (($#)); do
    case $1 in
        -p | --palette)
            palette=$(realpath "${2:?--palette needs a file}")
            shift 2
            ;;
        -S | --scheme)
            schemes+=("$(realpath "${2:?--scheme needs a file}")")
            shift 2
            ;;
        -P | --picture)
            picture=${2:?--picture needs a picture}
            shift 2
            ;;
        -s | --screenshot)
            mkdir -p "${2:?--screenshot needs a directory}"
            screenshots=$(realpath "$2")
            shift 2
            ;;
        -r | --render-only) render_only=true && shift ;;
        --hidden) hidden=true && shift ;;
        -k | --keep) keep=true && shift ;;
        -h | --help) usage && exit 0 ;;
        dark | light | mismatch | editor | vars-dark | vars-light) scenarios+=("$1") && shift ;;
        vars) scenarios+=(vars-dark vars-light) && shift ;;
        all) scenarios+=(dark light mismatch editor vars-dark vars-light) && shift ;;
        *) echo "libadwaita-live-test: unknown argument: $1 (see --help)" >&2 && exit 2 ;;
    esac
done
((${#scenarios[@]})) || scenarios=(dark light mismatch editor vars-dark vars-light)
sources=0
[[ -n $palette ]] && sources=$((sources + 1))
((${#schemes[@]})) && sources=$((sources + 1))
[[ -n $picture ]] && sources=$((sources + 1))
if ((sources > 1)); then
    echo "libadwaita-live-test: give one of --palette, --scheme, --picture" >&2 && exit 2
fi
if $hidden && [[ -z $screenshots ]]; then
    echo "libadwaita-live-test: --hidden needs --screenshot (there would be nothing to see)" >&2
    exit 2
fi
if ((${#schemes[@]} > 2)); then
    echo "libadwaita-live-test: --scheme takes one scheme or a dark and a light one" >&2 && exit 2
fi

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
if [[ -n $picture ]]; then
    palette=$work/palette.yaml
    # Your own config and library, unlike every other amo call here; printing a palette
    # changes nothing.
    (cd "$repo" && uv run --quiet amo --loglevel WARNING palette "$picture") >"$palette"
elif ((${#schemes[@]})); then
    palette=$work/palette.yaml
    amo palette --from-scheme "${schemes[@]}" >"$palette"
elif [[ -z $palette ]]; then
    palette=$work/palette.yaml
    amo palette --from-scheme "$assets/gruvbox-dark-hard.yaml" \
        "$assets/gruvbox-light-hard.yaml" >"$palette"
fi
echo "palette: $(sed -n 's/^name: //p' "$palette")"

# The variants the palette has: a single scheme gives one.
variants=()
for variant in dark light; do
    if grep -qx "  $variant:" "$palette"; then
        variants+=("$variant")
    fi
done
for variant in "${variants[@]}"; do
    amo theme apply --palette "$palette" --profile "$variant" --variant "$variant" --no-reload
    mkdir -p "$work/$variant/gtk-4.0" "$work/$variant-vars/gtk-4.0"
    cp "$work/amo-cache/theme/$variant/libadwaita.css" "$work/$variant/gtk-4.0/gtk.css"
    cp "$work/amo-cache/theme/$variant/libadwaita-vars.css" "$work/$variant-vars/gtk-4.0/gtk.css"
    echo "$variant: $work/$variant/gtk-4.0/gtk.css"
    echo "$variant (libadwaita-vars): $work/$variant-vars/gtk-4.0/gtk.css"
done

# A colour as rendered, for the checklist: colour DIR NAME.
colour() {
    sed -n "s/^@define-color $2 \(#[0-9a-f]*\);$/\1/p" "$work/$1/gtk-4.0/gtk.css"
}

# A variable as rendered: variable DIR NAME (without the --).
variable() {
    sed -n "s/^  --$2: \(#[0-9a-f]*\);$/\1/p" "$work/$1/gtk-4.0/gtk.css"
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
  - Tab View demo: tab colours are GNOME's (blue, green, ...): this template does not reach
    them (libadwaita-vars does).
  - Anything else in GNOME blue (#3584e4) is a colour the template does not reach.
EOF
}

vars_checklist() {
    local dir=$1-vars scheme=$2
    cat <<EOF
  - Unlike 'mismatch': accent ($(variable "$dir" accent-color)), success, warning and error text on the
    Style Classes demo readable on the window, as in '$1', though the scheme is $scheme.
  - Toggle Groups page: the active segment clearly apart from its track, on the window and on
    the cards alike, with readable text.
  - Animations page: the ball's gradient runs from green-2 $(variable "$dir" green-2) to green-5
    $(variable "$dir" green-5), not GNOME's #57e389 to #26a269.
  - Tab View demo: tab page hues from the palette (blue-3 $(variable "$dir" blue-3), red-3 $(variable "$dir" red-3),
    ...), not GNOME's. Their lightness is the demo's own, by scheme (92 % light, 20 % dark), so
    here they come out as for a $scheme scheme: expected, and why the colour-scheme hook stays.
  - Expected still $scheme: anything drawn from the scheme rather than the stylesheet (app CSS
    under prefers-color-scheme, icons and images an app picks per scheme).
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
        vars-dark)
            echo "== vars-dark: adwaita-1-demo on libadwaita-vars, dark variant, prefer-light"
            vars_checklist dark light
            ;;
        vars-light)
            echo "== vars-light: adwaita-1-demo on libadwaita-vars, light variant, prefer-dark"
            vars_checklist light dark
            ;;
    esac
}

# The palette variant a scenario renders.
variant_of() {
    case $1 in
        light | vars-light) echo light ;;
        *) echo dark ;;
    esac
}

# ADW_DEBUG_COLOR_SCHEME takes default, prefer-dark or prefer-light only (libadwaita 1.9); anything
# else is ignored with a warning, leaving the system's preference.
launch() {
    local scenario=$1 dir=$2 scheme=$3 app=$4
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
        XDG_CONFIG_HOME=$work/$dir ADW_DEBUG_COLOR_SCHEME=$scheme "$app" >/dev/null 2>&1 || true
        return
    fi
    local placement=()
    if $hidden; then
        placement=(--hidden)
        echo "  capturing into $screenshots, off screen"
    else
        echo "  capturing into $screenshots (keep this workspace visible; focus is yours)"
    fi
    # The tool launches the app itself. The system python3: PyGObject (Atspi) is not in the
    # project's venv.
    /usr/bin/env python3 -I "$repo/tools/libadwaita_screenshots.py" --app "$app" \
        --prefix "$scenario" "${placement[@]}" \
        --env "XDG_CONFIG_HOME=$work/$dir" --env "ADW_DEBUG_COLOR_SCHEME=$scheme" \
        "$screenshots" "$@"
}

vars_pages=("Toggle Groups" "Animations" "Tab View+Run the Demo" "Style Classes+Run the Demo")
for scenario in "${scenarios[@]}"; do
    echo
    variant=$(variant_of "$scenario")
    if [[ " ${variants[*]} " != *" $variant "* ]]; then
        echo "== $scenario: skipped, the palette has no $variant variant"
        continue
    fi
    describe "$scenario"
    $render_only && continue
    case $scenario in
        dark) launch dark dark prefer-dark adwaita-1-demo ;;
        light) launch light light prefer-light adwaita-1-demo ;;
        mismatch) launch mismatch dark default adwaita-1-demo "Style Classes+Run the Demo" ;;
        editor) launch editor dark prefer-dark gnome-text-editor ;;
        vars-dark) launch vars-dark dark-vars prefer-light adwaita-1-demo "${vars_pages[@]}" ;;
        vars-light) launch vars-light light-vars prefer-dark adwaita-1-demo "${vars_pages[@]}" ;;
    esac
done
