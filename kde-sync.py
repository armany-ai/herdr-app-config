#!/usr/bin/env python3
"""Sync KDE Plasma's accent color into the Pixel HQ layout of the Herdr app.

Reads ~/.config/kdeglobals ([General] AccentColor, which Plasma updates when the
accent follows the wallpaper) and writes it into:
  - layouts/pixel-hq-glass.json and/or layouts/pixel-hq.json (whichever exist):
    colors.accent, the focused-pane border, the sidebar's rim of light, the warm
    corner of the background gradient, the glass sheen of the sidebar and the
    panes, and the sidebar and pane corner radius from KWin (see window_radius)
  - themes/pixel-hq.json: the terminal cursor
The company-pane badges, the company-spaces train line and the company-agents
office read colors.accent; company-brand and company-pane follow the radius.

Only acts in a KDE Plasma session (see plasma_session); anywhere else it exits
without touching anything. Blue stays for activity ("typing"). Files are only
written when a value changes.
Run by the systemd user units herdr-kde-sync.path / .service.
"""
import configparser
import json
import os
import sys

HOME = os.path.expanduser("~")
KDEGLOBALS = os.path.join(HOME, ".config/kdeglobals")
APP = os.environ.get("HERDR_APP_HOME", os.path.join(HOME, ".config/herdr-app"))
LAYOUTS = [os.path.join(APP, f"layouts/{n}.json") for n in ("pixel-hq-glass", "pixel-hq")]
THEME = os.path.join(APP, "themes/pixel-hq.json")
BASE_BG = (0x11, 0x11, 0x1B)  # the layout's navy canvas, used when Kvantum isn't the widget style
KVANTUM = os.path.join(HOME, ".config/Kvantum")
SHEEN_PANE = "#ffffff1c"     # the light on a pane's top-left corner (white, ~11%)
SHEEN_SIDEBAR = "#ffffff26"  # and on the sidebar's (~15%)


def plasma_session():
    """(True, why) on a KDE Plasma desktop, (False, why) anywhere else.

    Off Linux (macOS, Windows) it never runs. On Linux the session's desktop
    decides, so logging into GNOME on a machine that also has Plasma leaves the
    layout alone; with no desktop variables (early at login) kdeglobals decides.
    """
    if not sys.platform.startswith("linux"):
        return False, f"not Linux ({sys.platform})"
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    if desktop:
        if "KDE" in desktop.upper().split(":"):
            return True, "Plasma"
        return False, f"desktop is {desktop}, not KDE Plasma"
    if os.environ.get("KDE_FULL_SESSION") == "true":
        return True, "Plasma"
    if os.path.exists(KDEGLOBALS):
        return True, "kdeglobals"
    return False, "no KDE Plasma session"


def kde_accent():
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read(KDEGLOBALS)
    for section, key in (("General", "AccentColor"), ("Colors:Selection", "BackgroundNormal")):
        raw = cp.get(section, key, fallback="").strip()
        if raw:
            try:
                rgb = tuple(int(x) for x in raw.split(",")[:3])
                if len(rgb) == 3:
                    return rgb
            except ValueError:
                pass
    return None


def read_ini(path):
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    try:
        cp.read(path)
    except configparser.Error:
        pass
    return cp


# --- Window corner radius -------------------------------------------------
# 1. KDE-Rounded-Corners (github.com/matinlotfali/KDE-Rounded-Corners), when KWin
#    has it loaded: kwinrc [Round-Corners] Size (active windows, default 20).
# 2. Otherwise the window decoration: Breeze rounds by a fixed
#    Frame_FrameRadius (2.5) x smallSpacing (2 on Wayland) = 5 px.
# 3. Unknown decoration: leave the layout's radius as it is.
SHAPECORNERS_IDS = ("kwin4_effect_shapecorners", "kwin_effect_shapecorners")
SHAPECORNERS_DEFAULT = 20
BREEZE_RADIUS = 5


def plugin_dirs():
    dirs = [d for d in os.environ.get("QT_PLUGIN_PATH", "").split(":") if d]
    for base in ("/usr/lib64", "/usr/lib", "/usr/local/lib64", "/usr/local/lib",
                 "/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu",
                 os.path.join(HOME, ".local/lib64"), os.path.join(HOME, ".local/lib")):
        dirs.append(os.path.join(base, "qt6/plugins"))
        dirs.append(os.path.join(base, "plugins"))
    return dirs


def shapecorners_installed():
    for d in plugin_dirs():
        for pid in SHAPECORNERS_IDS:
            if os.path.exists(os.path.join(d, "kwin/effects/plugins", pid + ".so")):
                return pid
    return None


def kwin_effect_loaded(pid):
    """True/False from KWin over D-Bus, None when KWin can't be asked."""
    import shutil
    import subprocess
    if shutil.which("gdbus"):
        cmd = ["gdbus", "call", "--session", "-d", "org.kde.KWin", "-o", "/Effects",
               "-m", "org.kde.kwin.Effects.isEffectLoaded", pid]
    elif shutil.which("dbus-send"):
        cmd = ["dbus-send", "--session", "--print-reply", "--dest=org.kde.KWin", "/Effects",
               "org.kde.kwin.Effects.isEffectLoaded", f"string:{pid}"]
    else:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return "true" in out.stdout.lower()


def kvantum_background():
    """(rgb, alpha 0..1, theme) of the Kvantum theme's window, or None.

    Only when Plasma's widget style is Kvantum. The theme comes from
    ~/.config/Kvantum/kvantum.kvconfig; its kvconfig is looked up in the user
    folder first, then system-wide. Alpha follows translucent_windows and
    reduce_window_opacity, so Herdr matches the translucency of Qt windows.
    """
    # kdeglobals overrides; Plasma falls back to the global theme's kdedefaults
    style = read_ini(KDEGLOBALS).get("KDE", "widgetStyle", fallback="") or \
        read_ini(os.path.join(HOME, ".config/kdedefaults/kdeglobals")).get("KDE", "widgetStyle", fallback="")
    style = style.strip().lower()
    if style != "kvantum" and style != "kvantum-dark":
        return None
    theme = read_ini(os.path.join(KVANTUM, "kvantum.kvconfig")).get("General", "theme", fallback="").strip()
    if not theme:
        return None
    base = theme.rstrip("#")
    candidates = [os.path.join(KVANTUM, theme, theme + ".kvconfig"),
                  os.path.join(KVANTUM, base, base + ".kvconfig")]
    for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":"):
        candidates.append(os.path.join(d, "Kvantum", base, base + ".kvconfig"))
    for path in candidates:
        if not os.path.exists(path):
            continue
        cfg = read_ini(path)
        raw = cfg.get("GeneralColors", "window.color", fallback="").strip().lstrip("#")
        if len(raw) < 6:
            return None
        try:
            rgb = tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None
        alpha = 1.0
        if cfg.get("%General", "translucent_windows", fallback="false").lower() == "true":
            try:
                alpha = 1 - max(0, min(90, int(cfg.get("%General", "reduce_window_opacity", fallback="0")))) / 100
            except ValueError:
                pass
        return rgb, alpha, theme
    return None


def window_radius():
    """(radius, source) or (None, reason)."""
    kwinrc = read_ini(os.path.join(HOME, ".config/kwinrc"))
    pid = shapecorners_installed()
    if pid:
        loaded = kwin_effect_loaded(pid)
        if loaded is None:  # no D-Bus: trust kwinrc (the effect is enabled by default)
            loaded = kwinrc.get("Plugins", pid + "Enabled", fallback="true").lower() != "false"
        if loaded:
            try:
                size = int(float(kwinrc.get("Round-Corners", "Size", fallback=str(SHAPECORNERS_DEFAULT))))
            except ValueError:
                size = SHAPECORNERS_DEFAULT
            return size, "Rounded Corners"
    library = kwinrc.get("org.kde.kdecoration2", "library", fallback="org.kde.breeze")
    if library == "org.kde.breeze":
        return BREEZE_RADIUS, "Breeze"
    return None, f"unknown decoration {library}"


def luminance(rgb):
    """WCAG relative luminance, 0 (black) .. 1 (white)."""
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def darkened(rgb, lightness=0.21, max_sat=0.25):
    """The same hue at a dark lightness, so the terminal's light text stays readable."""
    import colorsys
    h, _, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb))
    return tuple(c * 255 for c in colorsys.hls_to_rgb(h, lightness, min(s, max_sat)))


def hexc(rgb, alpha=None):
    s = "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)
    return s + (alpha or "")


def mix(a, b, k):
    return tuple(x * (1 - k) + y * k for x, y in zip(a, b))


def write_if_changed(path, data):
    new = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    try:
        old = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        old = None
    if old == new:
        return False
    tmp = path + ".kde-sync.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new)
    os.replace(tmp, path)
    return True


def main():
    ok, why = plasma_session()
    if not ok:
        print(f"kde-sync: skipped, {why}")
        return 0
    rgb = kde_accent()
    if not rgb:
        print("kde-sync: no accent color in kdeglobals", file=sys.stderr)
        return 1
    acc = hexc(rgb)

    radius, source = window_radius()
    kv = kvantum_background()
    if kv:
        kv_rgb, kv_alpha, kv_theme = kv
        light = luminance(kv_rgb) > 0.2
        if light:  # Pixel HQ's terminal text is light: keep the hue, not the brightness
            kv_rgb = darkened(kv_rgb)
        a = f"{round(kv_alpha * 255):02x}"
        dark = mix(kv_rgb, (0, 0, 0), 0.25)
        bg = {
            # the window: Kvantum's color and translucency, accent glow in the corner
            "gradient": [hexc(mix(kv_rgb, rgb, 0.22), a), hexc(kv_rgb, a)],
            "canvas": hexc(dark, "4d"), "background": hexc(kv_rgb, "4d"),
            "chrome": hexc(dark, "4d"), "pane": hexc(kv_rgb, "82"),
            "sidebar": hexc(dark, "4d"),
        }
        bgtxt = f"background Kvantum {kv_theme} {hexc(kv_rgb)}{' (light theme, darkened)' if light else ''} at {round(kv_alpha * 100)}%"
    else:
        bg = {"gradient": [hexc(mix(BASE_BG, rgb, 0.22), "a0"), "#11111b4d"],
              "canvas": "#11111b4d", "background": "#1e1e2e4d",
              "chrome": "#1818254d", "pane": "#1e1e2e82", "sidebar": "#1818254d"}
        bgtxt = "background navy (Kvantum not in use)"
    # Glass without blur: each card is its tint with a light sheen falling from
    # the top-left corner, and a thin rim of light (the sidebar's leans to the accent).
    bg["pane"] = {"gradient": [SHEEN_PANE, bg["pane"]], "angle": 160}
    bg["sidebar"] = {"gradient": [SHEEN_SIDEBAR, bg["sidebar"]], "angle": 160}
    bg["rim"] = hexc(mix(rgb, (255, 255, 255), 0.6), "40")
    layouts = [p for p in LAYOUTS if os.path.exists(p)]
    if not layouts:
        print("kde-sync: no Pixel HQ layout in " + APP, file=sys.stderr)
        return 1
    changed = [p for p in layouts if write_if_changed(p, apply_layout(p, acc, bg, radius))]

    theme = json.load(open(THEME, encoding="utf-8"))
    theme["cursor"] = acc
    if write_if_changed(THEME, theme):
        changed.append(THEME)

    rtxt = f"radius {radius} ({source})" if radius is not None else f"radius unchanged ({source})"
    print(f"kde-sync: accent {acc}; {rtxt}; {bgtxt}; " + (f"updated {', '.join(os.path.relpath(p, APP) for p in changed)}" if changed else "no changes"))
    return 0


def apply_layout(path, acc, bg, radius):
    layout = json.load(open(path, encoding="utf-8"))
    colors = layout.setdefault("colors", {})
    colors["accent"] = acc
    for key in ("canvas", "background", "chrome"):
        colors[key] = bg[key]
    for node in layout.get("children", []):
        if node.get("id") == "sidebar":
            node["background"] = bg["sidebar"]
            if isinstance(node.get("border"), dict):
                node["border"]["color"] = bg["rim"]

    if radius is not None:
        for node in layout.get("children", []):
            if node.get("id") == "sidebar":
                node["radius"] = radius

    def walk(n):
        pane = n.get("content", {}).get("pane") if isinstance(n.get("content"), dict) else None
        if isinstance(pane, dict):
            if "background" in pane:
                pane["background"] = bg["pane"]
            if isinstance(pane.get("focus"), dict):
                pane["focus"]["color"] = acc
            if radius is not None:
                pane["radius"] = radius
        for c in n.get("children", []):
            walk(c)

    walk(layout)
    layout["background"] = {"gradient": bg["gradient"], "angle": 160}
    return layout


if __name__ == "__main__":
    sys.exit(main())
