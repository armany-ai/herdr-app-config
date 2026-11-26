// Look: the status bar's popover for Pixel HQ's appearance (dark, light, or following the
// system's Kvantum theme), how see-through the window is, and how blurred what is behind it is.
// It owns no colors: it writes the choices to pixel-hq-look.json and runs kde-sync.py,
// which rewrites the layout; the script's "look: {...}" line says what is showing.
// Blur is the one thing it changes outside Herdr: the strength is KWin's own Blur effect
// setting (kwinrc), shared by every blurred window. 0 only turns this window's blur off.
import { View, div } from "gpui-kit";
import { v_flex, h_flex, SliderState, Slider, SliderTrack, SliderIndicator, SliderThumb } from "gpui-base";
import { theme, exec, appHome, readTextFile, writeTextFile, checking, nextCommand } from "herdr";

const MONO = "JetBrains Mono";
const MODES = [["dark", "Dark"], ["light", "Light"], ["system", "System"]];
const prefsFile = () => `${appHome()}/pixel-hq-look.json`;

export default class Look extends View {
  init(_props, cx) {
    this.look = null;     // kde-sync.py's report: { mode, appearance, transparency, auto, kvantum }
    this.mode = null;     // the choice just clicked, shown before the script answers
    this.value = 40;      // the slider's readout, percent
    this.error = null;
    this.busy = false;
    this.pending = null;  // choices made while the script was running
    this.slider = SliderState.new({ min: 0, max: 95, step: 1, value: this.value });
    this.slider.on("change", (v, cx) => { this.value = Math.round(v); cx.notify(); });
    this.slider.on("release", (v, cx) => this.save({ transparency: Math.round(v) }, cx));
    this.blur = 15;       // the blur slider's readout: 0 is off, 1..15 is KWin's strength
    this.blurSlider = SliderState.new({ min: 0, max: 15, step: 1, value: this.blur });
    this.blurSlider.on("change", (v, cx) => { this.blur = Math.round(v); cx.notify(); });
    this.blurSlider.on("release", (v, cx) => {
      const n = Math.round(v);
      this.save(n > 0 ? { blur: true, kwin_blur: n } : { blur: false }, cx);
    });
    if (checking()) return;
    this.save({}, cx);    // nothing to change: runs the script once to learn what is showing
    // company-look.dark / .light / .system / .blur-<0..15>, from a key or `herdr-app do`, while this is open.
    cx.spawn(async (cx) => {
      for (;;) {
        const command = String(await nextCommand()).split(/[.:]/).pop();
        if (MODES.some(([id]) => id === command)) { this.mode = command; cx.notify(); this.save({ mode: command }, cx); }
        const blur = /^blur-(\d+)$/.exec(command);  // company-look.blur-0 (off) .. blur-15
        if (blur) {
          const n = Math.min(15, Number(blur[1]));
          this.blur = n; this.blurSlider.set_value(n); cx.notify();
          this.save(n > 0 ? { blur: true, kwin_blur: n } : { blur: false }, cx);
        }
      }
    });
  }

  // Merges the choices into the file and applies them. Calls made meanwhile are folded
  // into one more run, so a quick series of clicks ends on the last one.
  save(patch, cx) {
    this.pending = { ...(this.pending ?? {}), ...patch };
    if (this.busy) return;
    this.busy = true;
    cx.spawn(async (cx) => {
      try {
        while (this.pending) {
          const { kwin_blur, ...next } = this.pending;
          this.pending = null;
          let failed = null;
          if (kwin_blur) {
            // KWin's own setting, then ask the running effect to read it again.
            const set = await exec("kwriteconfig6", ["--file", "kwinrc", "--group", "Effect-blur", "--key", "BlurStrength", String(kwin_blur)], { timeout: 10000 });
            const apply = set.code === 0
              ? await exec("busctl", ["--user", "call", "org.kde.KWin", "/Effects", "org.kde.kwin.Effects", "reconfigureEffect", "s", "blur"], { timeout: 10000 })
              : set;
            if (apply.code !== 0) failed = (apply.stderr || "could not change KWin's blur").trim().split("\n").pop();
          }
          if (Object.keys(next).length > 0) {
            const old = await readTextFile(prefsFile());
            let prefs = {};
            try { prefs = JSON.parse(old ?? "{}"); } catch { prefs = {}; }
            if (!prefs || typeof prefs !== "object" || Array.isArray(prefs)) prefs = {};
            await writeTextFile(prefsFile(), JSON.stringify({ ...prefs, ...next }, null, 2) + "\n", old);
          }
          const r = await exec("python3", [`${appHome()}/kde-sync.py`], { timeout: 15000 });
          const line = r.stdout.split("\n").find((l) => l.startsWith("look: "));
          if (r.code !== 0 || !line) {
            this.error = (r.stderr || r.stdout || "kde-sync.py gave no answer").trim().split("\n").pop();
          } else {
            this.error = failed;
            this.look = JSON.parse(line.slice(6));
            this.mode = null;
            this.value = this.look.transparency;
            this.slider.set_value(this.value);
            this.blur = this.look.blur === false ? 0 : (this.look.blur_strength ?? 15);
            this.blurSlider.set_value(this.blur);
          }
          cx.notify();
        }
      } catch (e) {
        this.error = String(e?.message ?? e);
      }
      this.busy = false;
      cx.notify();
    });
  }

  render() {
    const t = theme();
    const acc = /^#[0-9a-f]{6}/i.test(t.accent ?? "") ? t.accent.slice(0, 7) : "#e8395e";
    const mode = this.mode ?? this.look?.mode ?? "system";
    const label = (text) => div().font_bold().text_size(10).text_color(t.dim).child(text.toUpperCase());
    const segment = ([id, name]) => div().id(`look-mode-${id}`).flex_1().h(26).flex().items_center().justify_center()
      .cursor_pointer().rounded(8).border_1()
      .border_color(mode === id ? acc : t.border).bg(mode === id ? acc + "26" : t.hover)
      .font_bold().text_size(10).text_color(mode === id ? t.foreground : t.muted)
      .hover((s) => s.text_color(t.foreground))
      .on_click((_e, cx) => { this.mode = id; cx.notify(); this.save({ mode: id }, cx); })
      .child(name.toUpperCase());
    const following = this.look
      ? (mode === "system"
        ? (this.look.kvantum ? `Following Kvantum: ${this.look.kvantum} (${this.look.appearance})` : "No Kvantum theme: dark")
        : `Always ${mode}`)
      : "…";
    const auto = this.look?.auto ?? true;
    // The thumb is centered on the value, so the part that measures it sits half a thumb (7px)
    // inside each end: at 0 and at the maximum the thumb stops flush with the groove instead of
    // hanging over it. The groove itself, and the start of the fill, are drawn edge to edge behind.
    // The groove is a tint of the text color, so the empty part shows on dark and on light glass.
    const groove = /^#[0-9a-f]{6}$/i.test(t.muted ?? "") ? t.muted + "38" : t.raised;
    const track = (state, filled) => div().relative().w_full().h(20)
      .child(div().absolute().left(0).right(0).top(7).h(6).rounded(3).bg(groove))
      .when(filled, (el) => el.child(div().absolute().left(0).top(7).w(12).h(6).rounded(3).bg(acc)))
      .child(v_flex().absolute().left(7).right(7).top(0).bottom(0).child(
        Slider.new(state).child(
          SliderTrack.new(state).flex().items_center().h(20).w_full().child(
            SliderIndicator.new(state).relative().w_full().h(6)
              .range_style((fill) => fill.bg(acc))
              .child(SliderThumb.new(state).size(14).rounded(7).bg(t.foreground).ml(-7).mt(-4))))));  // 14px on a 6px groove
    const blurHint = this.look?.blur_effect === false
      ? "KWin's Blur effect is off (Desktop Effects)"
      : this.blur === 0 ? "Off: sharp background, this window only" : "KWin's blur: changes every blurred window";
    return v_flex().id("look-root").size_full().p(12).gap(8).rounded(12)
      .bg(t.popover).border_1().border_color(t.input ?? t.border)
      .font_family(MONO).text_size(11).text_color(t.foreground)
      .on_mouse_down("left", (_e, cx) => cx.stop_propagation())
      .child(label("Appearance"))
      .child(h_flex().gap(6).children(MODES.map(segment)))
      .child(div().truncate().text_size(10).text_color(t.dim).child(following))
      .child(h_flex().mt(4).items_center().justify_between()
        .child(label("Transparency"))
        .child(h_flex().gap(8).items_center()
          .when(!auto, (el) => el.child(div().id("look-auto").px(6).h(18).flex().items_center().cursor_pointer().rounded(6)
            .border_1().border_color(t.border).font_bold().text_size(9.5).text_color(t.muted)
            .hover((s) => s.text_color(t.foreground))
            .tooltip("Back to the Kvantum theme's own translucency")
            .on_click((_e, cx) => this.save({ transparency: null }, cx))
            .child("AUTO")))
          .child(div().font_bold().text_color(t.foreground).child(`${this.value}%`))))
      .child(track(this.slider, this.value > 0))
      .child(div().text_size(10).text_color(t.dim)
        .child(auto ? "Auto: the Kvantum theme's own" : "0% is solid, 95% is almost clear"))
      .child(h_flex().mt(4).items_center().justify_between()
        .child(label("Blur"))
        .child(div().font_bold().text_color(t.foreground).child(this.blur === 0 ? "OFF" : `${this.blur} / 15`)))
      .child(track(this.blurSlider, this.blur > 0))
      .child(div().text_size(10).text_color(this.error ? (t.blocked ?? "#f38ba8") : t.dim)
        .child(this.error ?? blurHint));
  }
}
