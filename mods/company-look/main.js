// Look: the status bar's popover for Pixel HQ's appearance (dark, light, or following the
// system's Kvantum theme) and how see-through the window is.
// It owns no colors: it writes the two choices to pixel-hq-look.json and runs kde-sync.py,
// which rewrites the layout; the script's "look: {...}" line says what is showing.
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
    if (checking()) return;
    this.save({}, cx);    // nothing to change: runs the script once to learn what is showing
    // company-look.dark / .light / .system, from a key or `herdr-app do`, while this is open.
    cx.spawn(async (cx) => {
      for (;;) {
        const command = String(await nextCommand()).split(/[.:]/).pop();
        if (MODES.some(([id]) => id === command)) { this.mode = command; cx.notify(); this.save({ mode: command }, cx); }
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
          const next = this.pending;
          this.pending = null;
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
            this.error = null;
            this.look = JSON.parse(line.slice(6));
            this.mode = null;
            this.value = this.look.transparency;
            this.slider.set_value(this.value);
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
      .child(Slider.new(this.slider).child(
        SliderTrack.new(this.slider).flex().items_center().h(20).w_full().child(
          SliderIndicator.new(this.slider).relative().w_full().h(6).rounded(3).bg(t.raised)
            .range_style((fill) => fill.rounded(3).bg(acc))
            .child(SliderThumb.new(this.slider).size(14).rounded(7).bg(t.foreground).ml(-7)))))
      .child(div().text_size(10).text_color(this.error ? (t.blocked ?? "#f38ba8") : t.dim)
        .child(this.error ?? (auto ? "Auto: the Kvantum theme's own" : "0% is solid, 95% is almost clear")));
  }
}
