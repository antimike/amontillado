# GTK theming

How to make GTK apps follow the palette amontillado applies: GTK3 apps recoloured live on every
`amo theme apply`, and GTK4 (libadwaita) apps at their next start. One setup, end to end. The
paths use the default cache, `${XDG_CACHE_HOME:-$HOME/.cache}/theme`; adjust if `theme.cache`
says otherwise.

## What you need

- **adw-gtk3**, the libadwaita look for GTK3 (Fedora: `adw-gtk3-theme`; elsewhere, its releases
  under `~/.local/share/themes`). Its widgets read libadwaita's colour names, which is what lets
  amontillado's `@define-color`s take over.
- **`gsettings`** and a session whose GTK3 apps follow `org.gnome.desktop.interface gtk-theme`:
  GNOME, or a Wayland compositor (Hyprland, sway) with xdg-desktop-portal-gtk or gsd-xsettings
  running. Under X11 without them, GTK3 reads the theme from XSETTINGS instead (xsettingsd's
  `Net/ThemeName`), which `amo hook gtk3-theme` does not set.
- For GTK4, nothing beyond libadwaita itself.

## The config

```yaml
theme:
  apps:
    libadwaita:                # gtk-3.0: libadwaita.css, under adw-gtk3
      reload: amo hook gtk3-theme
    gtk4:                      # gtk-4.0: libadwaita-vars.css
      template: libadwaita-vars
      reload: 'gsettings set org.gnome.desktop.interface color-scheme "prefer-$AMO_VARIANT"'
```

Two apps, because GTK3 cannot read the GTK4 file: GTK3 fails on the `:root` block of CSS
variables that `libadwaita-vars` adds, so `libadwaita` (`@define-color` only) serves GTK3 and
`libadwaita-vars` serves GTK4. Both hold the same colours (a test keeps them equal). `amo config
check` names `gsettings` or adw-gtk3 when the hook is configured without them.

Then link the GTK4 file once:

```sh
mkdir -p ~/.config/gtk-4.0
ln -sf ~/.cache/theme/current/libadwaita-vars.css ~/.config/gtk-4.0/gtk.css
```

and run `amo theme apply` (with a picture or `--palette`). The first run of the hook writes the
GTK3 theme (below) and selects it.

## GTK3, live

GTK3 reads a theme's `gtk.css` when the theme is loaded, and loads it again when the desktop's
`gtk-theme` setting changes. Running apps do not watch the file. So the live reload has two
parts: a theme whose `gtk.css` always points at the applied colours, and a reload that makes
apps load it again.

### The theme

`amo hook gtk3-theme` writes, when missing, one theme per variant:

```text
~/.local/share/themes/amontillado-dark/gtk-3.0/gtk.css
~/.local/share/themes/amontillado-light/gtk-3.0/gtk.css
```

Each imports adw-gtk3 and then the applied colours (shown for dark, with `HOME=/home/me`):

```css
@import url("file:///usr/share/themes/adw-gtk3-dark/gtk-3.0/gtk.css");
@import url("file:///home/me/.cache/theme/current/libadwaita.css");
```

- adw-gtk3 first, so the second file's `@define-color`s override its colours.
- Absolute `file://` URLs: a relative `@import` resolves against the path GTK loaded, so a theme
  under `~/.local/share/themes` would look for the files beside itself.
- The colours through `current`, the cache's link to the applied profile, so every reload reads
  the profile `amo theme apply` just swapped in.
- adw-gtk3 is found under the `themes` directory of `$XDG_DATA_HOME`, then each of
  `$XDG_DATA_DIRS`, as GTK searches them; `adw-gtk3-dark` for the dark theme.

An existing `gtk.css` is never overwritten (the hook warns when it differs from what it would
write). Delete it to have the next apply write it again, for example after moving the cache or
adw-gtk3.

### The reload

`amo hook gtk3-theme` runs as the libadwaita app's reload, so `AMO_VARIANT` is the variant that
file was rendered in. It sets `gtk-theme` to `amontillado-$AMO_VARIANT`. Setting a value that is
already there notifies no one, and after the first apply the value usually is already there, so
the hook then sets `Adwaita` first and the theme straight after: running GTK3 windows flash once
and come back in the new colours. It exits 1 and leaves `gtk-theme` alone when `gsettings` or
adw-gtk3 is missing (a failing reload only warns). `amo hook gtk3-theme --dry-run` prints what it
would write and set.

Checked 2026-11-21: a running GTK3 window in a headless sway session recoloured dark to light
to dark on `amo theme apply --app libadwaita`, without a restart.

### Buttons and selections

adw-gtk3 6.4 hard-codes white text on suggested-action buttons and the terminal selection, all
on the accent. A dark variant's accent is light, so that text was white on light blue. The
built-in `libadwaita` and `libadwaita-vars` templates set those to `accent_fg_color` (measured
11.72:1 dark, 4.88:1 light). adw-gtk3's other white text sits on its own near-black OSD
backgrounds and does not depend on the palette.

## GTK4 (libadwaita)

libadwaita apps ignore `gtk-theme`. They read `~/.config/gtk-4.0/gtk.css` at start, so the link
above themes every libadwaita app started after an apply; running ones keep their colours until
restarted. `libadwaita-vars` sets libadwaita's named colours, its CSS variables (the accent,
success, warning, error and destructive text, the toggle group, GNOME's `--blue-1` …
`--dark-5`) and pins the standalone text colours, so they hold whatever the desktop's colour
scheme says ([design.md](design.md), "Template sources").

The reload on the `gtk4` app keeps the colour scheme in step with the variant anyway: GtkSourceView
styles, per-scheme icons and illustrations, and apps' own CSS still follow the scheme. The
reasons, and other ways to set it (darkman), are in
[colour-scheme-hooks.md](colour-scheme-hooks.md).

Measured 2026-11-21 with this setup: the accent, success, warning, error and destructive text
reach at least 6.6:1 in dark and 4.58:1 in light on the window, view and card backgrounds, and
adwaita-1-demo loads the file without CSS errors.

## Limits

- Only sessions where GTK3 follows `gtk-theme` through gsettings (see "What you need").
- One flash per apply in running GTK3 windows, from the flip through Adwaita.
- GTK3 apps that set their own theme (`GTK_THEME` in their environment, a Flatpak without the
  theme exported) do not follow.
- libadwaita apps recolour at their next start, not live.

## Alternatives considered

Other ways to theme GTK3 from a palette, and why amontillado does not use them:

| Tool | Why not |
|---|---|
| adw-gtk3 alone | Fixed colours. It is the base here: amontillado only overrides its colours. |
| wpgtk | Its own pywal pipeline and theme templates, not amontillado's palette. |
| base16-gtk-flatcolor | A hand-patched legacy theme. |
| Gradience | Archived (2024). |
| Themix / oomox | Rebuilds a theme with sassc on every change: slow for every apply. |
| A user `~/.config/gtk-3.0/gtk.css` | Read at app start only: not live. |
