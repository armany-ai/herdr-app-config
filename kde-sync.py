#!/usr/bin/env python3
"""Sync KDE Plasma's accent color into the Pixel HQ layout of the Herdr app.

Reads ~/.config/kdeglobals ([General] AccentColor, which Plasma updates when the
accent follows the wallpaper) and writes it into:
  - layouts/pixel-hq-glass.json and/or layouts/pixel-hq.json (whichever exist):
    colors.accent, the focused-pane border, the sidebar's rim of light, the warm
    corner of the background gradient, the glass sheen of the sidebar and the
    panes, and the sidebar and pane corner radius from KWin (see window_radius)
  - themes/pixel-hq.json and themes/pixel-hq-light.json: the terminal cursor
Under a light Kvantum theme the layout turns light: light cards and panel colors,
and the layout's theme set to pixel-hq-light (dark text); a dark one sets pixel-hq.
The company-pane badges, the company-spaces train line and the company-agents
office read colors.accent; company-brand and company-pane follow the radius.

The status bar's Look popover (mods/company-look) can override two things, kept in
pixel-hq-look.json: the appearance (dark or light instead of following Kvantum) and
how see-through the window is.

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
# The terminal themes: the dark one, and the light one shown under a light Kvantum theme.
THEME_DARK, THEME_LIGHT = "pixel-hq", "pixel-hq-light"
THEMES = [os.path.join(APP, f"themes/{n}.json") for n in (THEME_DARK, THEME_LIGHT)]
# What the person picks in the status bar's Look popover (mods/company-look writes it):
# {"mode": "system" | "dark" | "light", "transparency": 0..95 or null}
LOOK = os.path.join(APP, "pixel-hq-look.json")
INK, PAPER = (0x2e, 0x34, 0x40), (0xec, 0xef, 0xf4)  # stand-ins when a theme has no usable color
BASE_BG = (0x11, 0x11, 0x1B)  # the layout's navy canvas, used when Kvantum isn't the widget style
KVANTUM = os.path.join(HOME, ".config/Kvantum")
# Dark look (a dark Kvantum theme): Kvantum's own color and translucency, as Qt windows show them.
GLOW_DARK = 0.22             # accent in the window's warm corner
SHEEN_DARK = ("#ffffff1c", "#ffffff26")  # see-through light on a pane's / the sidebar's top-left corner
RIM_PANE_DARK = "#ffffff30"  # the edge of light around an unfocused pane
RIM_ALPHA_DARK = "40"        # and around the sidebar, where it leans to the accent
# Panel colors the layout overrides, per appearance. The light set is longer: it also has
# to beat settings.json's colors (text, status, menus), which are meant for dark glass.
# Its surfaces and text are shades of Kvantum's window and text colors, added in main().
UI_DARK = {"surface": "#262637", "raised": "#313244", "border": "#ffffff14",
           "hover": "#ffffff10", "selected": "#ffffff14"}
UI_LIGHT = {"border": "#00000024", "input": "#00000047", "hover": "#0000000f", "selected": "#00000017",
            "working": "#1e66f5", "blocked": "#c2410c", "done": "#2f8a1f"}
UI_LIGHT_DERIVED = ("surface", "raised", "popover", "selection", "foreground", "muted", "dim", "idle")
# Light look (a light Kvantum theme): light glass with dark text. The window is a little
# clearer than Qt's and its tint leans to ice blue; the cards are denser so text stays readable.
WINDOW_CLARITY_LIGHT = 0.75  # window opacity = Kvantum's x this (60% -> 45%)
ICE = (90, 165, 235)         # the cool hue mixed into every tint
COOL = 0.34                  # how much of it; 0 keeps Kvantum's own color
GLOW_LIGHT = 0.10            # accent in the window's warm corner
SHEEN_PANE = 0.22            # how much white lightens a pane's top-left corner
SHEEN_SIDEBAR = 0.26         # and the sidebar's
PANE_ALPHA = "a0"            # a pane's tint (63%)
SIDEBAR_ALPHA = "8c"         # the sidebar's (55%)
RIM_PANE_LIGHT = "#ffffff73" # the edge of light around an unfocused pane
RIM_ALPHA_LIGHT = "80"       # and around the sidebar, where it leans to the accent


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


def look_prefs():
    """(mode, transparency): mode is "system" (follow Kvantum), "dark" or "light";
    transparency is how see-through the window is, 0..95 percent, or None for Kvantum's own."""
    try:
        d = json.load(open(LOOK, encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    mode = d.get("mode") if d.get("mode") in ("dark", "light") else "system"
    t = d.get("transparency")
    t = max(0.0, min(95.0, float(t))) if isinstance(t, (int, float)) and not isinstance(t, bool) else None
    return mode, t


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
    """(rgb, alpha 0..1, theme, text rgb) of the Kvantum theme's window, or None.

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
    # KDE_SYNC_KVANTUM_THEME=<name> tries a theme (a light one, say) without switching Plasma's.
    theme = os.environ.get("KDE_SYNC_KVANTUM_THEME", "").strip() or \
        read_ini(os.path.join(KVANTUM, "kvantum.kvconfig")).get("General", "theme", fallback="").strip()
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
        raw = cfg.get("GeneralColors", "window.text.color", fallback="").strip().lstrip("#")
        try:
            text = tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4)) if len(raw) >= 6 else None
        except ValueError:
            text = None
        return rgb, alpha, theme, text
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
    mode, transparency = look_prefs()
    kv = kvantum_background()
    white = (255, 255, 255)
    light = False
    if kv:
        kv_rgb, kv_alpha, kv_theme, kv_text = kv
        # A light Kvantum theme makes Pixel HQ light too: light cards, the light terminal theme.
        light = luminance(kv_rgb) > 0.2
    if mode != "system" and (mode == "light") != light:
        # The person chose the other appearance. A theme's text color is, near enough, the
        # window color of its opposite (Utterly-Nord and Utterly-Nord-Light swap the two).
        light = mode == "light"
        if kv:
            fits = kv_text and (luminance(kv_text) > 0.2) == light
            kv_rgb, kv_text = (kv_text if fits else (PAPER if light else INK)), kv_rgb
        else:  # no Kvantum: light glass from the stand-ins; dark keeps the navy look below
            kv = True
            kv_rgb, kv_alpha, kv_theme, kv_text = PAPER, 0.6, "none", INK
    # Transparency: the window's opacity, and every tint scaled with it (f = 1 keeps the tuned look).
    ref = kv_alpha if kv else 0xa0 / 255
    win = ref if transparency is None else 1 - transparency / 100
    f = win / ref if ref else 1.0

    def al(alpha):  # a tuned two-digit hex alpha, thinner or denser by f
        return f"{max(0, min(255, round(int(alpha, 16) * f))):02x}"

    if kv and light:
        clarity = WINDOW_CLARITY_LIGHT
        a = f"{round(win * clarity * 255):02x}"
        kv_rgb = mix(kv_rgb, ICE, COOL)
        card = mix(kv_rgb, white, 0.35)  # the cards: lighter and denser than the window
        ink = kv_text if kv_text and luminance(kv_text) < 0.2 else (0x2e, 0x34, 0x40)
        paper = mix(kv_rgb, white, 0.55)
        bg = {
            "gradient": [hexc(mix(kv_rgb, rgb, GLOW_LIGHT), a), hexc(kv_rgb, a)],
            "canvas": hexc(card, al("4d")), "background": hexc(kv_rgb, al("4d")),
            "chrome": hexc(card, al("4d")),
            # the sheen lightens the tint without thinning it, so the wallpaper stays behind the text
            "pane": [hexc(mix(card, white, SHEEN_PANE), al(PANE_ALPHA)), hexc(card, al(PANE_ALPHA))],
            "sidebar": [hexc(mix(card, white, SHEEN_SIDEBAR), al(SIDEBAR_ALPHA)), hexc(card, al(SIDEBAR_ALPHA))],
            "rim": hexc(mix(rgb, white, 0.6), RIM_ALPHA_LIGHT), "rim_pane": RIM_PANE_LIGHT,
            # the status bar's dark text sits on the clear window: give it a strip of light glass
            "bar": hexc(card, al("99")),
            "ui": dict(UI_LIGHT, surface=hexc(paper), raised=hexc(mix(kv_rgb, (0, 0, 0), 0.06)),
                       popover=hexc(mix(kv_rgb, white, 0.75)),
                       selection=hexc(mix(kv_rgb, (0, 0, 0), 0.18)),
                       foreground=hexc(ink), muted=hexc(mix(ink, paper, 0.25)),
                       dim=hexc(mix(ink, paper, 0.48)), idle=hexc(mix(ink, paper, 0.55))),
        }
        bgtxt = f"background Kvantum {kv_theme} (light) cooled to {hexc(kv_rgb)} at {round(win * clarity * 100)}%"
    elif kv:
        a = f"{round(win * 255):02x}"
        dark = mix(kv_rgb, (0, 0, 0), 0.25)
        bg = {
            # the window: Kvantum's color and translucency, accent glow in the corner
            "gradient": [hexc(mix(kv_rgb, rgb, GLOW_DARK), a), hexc(kv_rgb, a)],
            "canvas": hexc(dark, al("4d")), "background": hexc(kv_rgb, al("4d")),
            "chrome": hexc(dark, al("4d")),
            "pane": [SHEEN_DARK[0], hexc(kv_rgb, al("82"))], "sidebar": [SHEEN_DARK[1], hexc(dark, al("4d"))],
            "rim": hexc(mix(rgb, white, 0.6), RIM_ALPHA_DARK), "rim_pane": RIM_PANE_DARK,
            "ui": UI_DARK,
        }
        bgtxt = f"background Kvantum {kv_theme} (dark) {hexc(kv_rgb)} at {round(win * 100)}%"
    else:
        bg = {"gradient": [hexc(mix(BASE_BG, rgb, 0.22), al("a0")), "#11111b" + al("4d")],
              "canvas": "#11111b" + al("4d"), "background": "#1e1e2e" + al("4d"),
              "chrome": "#181825" + al("4d"),
              "pane": [SHEEN_DARK[0], "#1e1e2e" + al("82")], "sidebar": [SHEEN_DARK[1], "#181825" + al("4d")],
              "rim": hexc(mix(rgb, white, 0.6), RIM_ALPHA_DARK), "rim_pane": RIM_PANE_DARK,
              "ui": UI_DARK}
        bgtxt = "background navy (Kvantum not in use)"
    # Glass without blur: each card is its tint with a sheen of light falling from the
    # top-left corner, and a rim of light (the sidebar's leans to the accent).
    bg["pane"] = {"gradient": bg["pane"], "angle": 160}
    bg["sidebar"] = {"gradient": bg["sidebar"], "angle": 160}
    bg["theme"] = THEME_LIGHT if light and os.path.exists(THEMES[1]) else THEME_DARK
    layouts = [p for p in LAYOUTS if os.path.exists(p)]
    if not layouts:
        print("kde-sync: no Pixel HQ layout in " + APP, file=sys.stderr)
        return 1
    changed = [p for p in layouts if write_if_changed(p, apply_layout(p, acc, bg, radius))]

    for path in THEMES:
        if not os.path.exists(path):
            continue
        theme = json.load(open(path, encoding="utf-8"))
        theme["cursor"] = acc
        if write_if_changed(path, theme):
            changed.append(path)

    rtxt = f"radius {radius} ({source})" if radius is not None else f"radius unchanged ({source})"
    print(f"kde-sync: accent {acc}; {rtxt}; {bgtxt}; " + (f"updated {', '.join(os.path.relpath(p, APP) for p in changed)}" if changed else "no changes"))
    # one line for the Look popover: what is showing, and what "system" would give
    print("look: " + json.dumps({"mode": mode, "appearance": "light" if light else "dark",
                                 "transparency": round(100 - win * 100), "auto": transparency is None,
                                 "system_transparency": round(100 - ref * 100),
                                 "kvantum": kv_theme if kv else None}))
    return 0


def apply_layout(path, acc, bg, radius):
    layout = json.load(open(path, encoding="utf-8"))
    colors = layout.setdefault("colors", {})
    colors["accent"] = acc
    for key in ("canvas", "background", "chrome"):
        colors[key] = bg[key]
    for key in (*UI_LIGHT, *UI_LIGHT_DERIVED):  # a dark look drops what only the light one sets
        if key not in bg["ui"]:
            colors.pop(key, None)
    colors.update(bg["ui"])
    layout["theme"] = bg["theme"]
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
        if n.get("id") == "status":  # a strip behind the status bar, only under a light theme
            if "bar" in bg:
                n["background"], n["radius"] = bg["bar"], 10
            else:
                n.pop("background", None)
                n.pop("radius", None)
        pane = n.get("content", {}).get("pane") if isinstance(n.get("content"), dict) else None
        if isinstance(pane, dict):
            if "background" in pane:
                pane["background"] = bg["pane"]
            if isinstance(pane.get("border"), dict):
                pane["border"]["color"] = bg["rim_pane"]
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
