import { View, div } from "gpui-kit";
import { agents, panes, focused, shared, run, exec, props, theme, nextCommand, openOverlay, closeOverlay, notify } from "herdr";

// Layout copies track focus. Overlay runners also work in layouts without a bridge.
const memory = () => globalThis.__legacy_keys_v3 ??= { current: null, previous: null, queue: Promise.resolve() };
export default class LegacyKeys extends View {
  init(_props, cx) {
    this.command = props()?.command;
    this.handle = cx.focus_handle();
    this.prefix = Boolean(props()?.prefix || (props()?.overlay && !this.command));
    this.track();
    if (this.command) {
      const owner = props()?.overlay;
      cx.spawn(async () => {
        try {
          await this.action(this.command);
        } catch (error) {
          notify({ title: "Shortcut failed", body: String(error), level: "error" });
        } finally { if (owner) closeOverlay(owner); }
      });
    } else if (this.prefix) this.handle.focus();
    else cx.spawn(async (cx) => {
      for (;;) {
        const command = await nextCommand();
        if (command === "prefix") openOverlay({ mod: "legacy-keys", kind: "popup", width: 510, height: 90, props: { prefix: true } });
        else {
          // Serialize commands so two fast navigation keys don't race.
          memory().queue = memory().queue.catch(() => {}).then(() => this.action(command)).catch(error => notify({ title: "Shortcut failed", body: String(error), level: "error" }));
          await memory().queue;
        }
        cx.notify();
      }
    });
  }

  track() {
    const current = focused()?.pane;
    const mem = memory();
    if (current && current !== mem.current) { mem.previous = mem.current; mem.current = current; }
  }

  async call(command, args = {}) {
    const result = await exec("herdr-app", ["do", command, JSON.stringify(args)]);
    if (result.code !== 0) throw new Error(result.stderr || result.stdout);
    return JSON.parse(result.stdout);
  }

  async action(command) {
    if (command.startsWith("agent-")) {
      let list = agents();
      const saved = shared("legacy.agent-order") ?? [];
      // Custom sidebars publish their exact order; stock layouts need a live fallback.
      if (["persona5", "main-mods", "legacy"].includes(shared("layout"))) {
        const byAddress = new Map(list.map(a => [a.address, a]));
        list = [...saved.map(address => byAddress.get(address)).filter(Boolean), ...list.filter(a => !saved.includes(a.address))];
      } else {
        const rank = { blocked: 4, done: 3, working: 2, idle: 1 };
        if ((shared("agents.sort") ?? "priority") === "priority") list.sort((a,b) => (rank[b.status] ?? 0) - (rank[a.status] ?? 0) || b.seq-a.seq);
        list = [...list.filter(a => a.pinned), ...list.filter(a => !a.pinned)];
      }
      const agent = list[Number(command.slice(6)) - 1];
      if (agent) run("agent.focus", { terminal: agent.address });
    } else if (command === "attention") {
      const rank = { blocked: 0, done: 1, idle: 2 };
      const list = agents().filter(a => a.status in rank).sort((a, b) => rank[a.status] - rank[b.status] || b.seq - a.seq);
      const index = list.findIndex(a => a.address === memory().attention);
      const next = list[(index + 1) % list.length];
      if (next) { memory().attention = next.address; run("agent.focus", { terminal: next.address }); }
    } else if (command === "last") {
      if (panes().some(p => p.pane === memory().previous)) run("pane.focus", { pane: memory().previous });
    } else if (command.startsWith("focus-")) {
      const direction = command.slice(6);
      const before = focused()?.pane;
      if (!before) return;
      await this.call("pane.go", { direction });
      const result = await exec("herdr-app", ["status"]);
      if (result.code !== 0) throw new Error(result.stderr);
      if (JSON.parse(result.stdout).focused_pane === before) await this.call(direction === "left" ? "tab.prev" : "tab.next");
    } else if (command.startsWith("split-")) {
      const direction = command.slice(6);
      const negative = direction === "left" || direction === "up";
      await this.call("pane.split", { direction: direction === "left" ? "right" : direction === "up" ? "down" : direction });
      if (negative) await this.call("pane.swap", { direction });
    } else if (command === "unsupported") {
      notify({ title: "Legacy shortcut unavailable", body: "This Herdr version has no pane resize mode, external scrollback editor, or Zoetrope plugin API.", level: "info" });
    } else {
      const [name, value] = command.split(":");
      run(name, value === undefined ? {} : name.endsWith("select") ? { index: Number(value) } : name === "layout.toggle" ? { id: value } : { name: value });
    }
  }

  render(cx) {
    if (!this.prefix) { this.track(); return div(); }
    const t = theme();
    return div().id("legacy-prefix").track_focus(this.handle).p(14).bg(t.popover).text_color(t.foreground).text_size(13)
      .child("Ctrl+B → h/j/k/l split · c new tab · z/f zoom · Esc cancel")
      .on_key_down((event, cx) => {
        cx.stop_propagation();
        const key = event.keystroke;
        closeOverlay(props().overlay);
        if (key === "escape") return;
        let command = {
          h: "split-left", j: "split-down", k: "split-up", l: "split-right",
          z: "pane.zoom", f: "pane.zoom", c: "tab.new", p: "tab.prev", left: "tab.prev", n: "tab.next", right: "tab.next",
          "shift-t": "tab.rename", ",": "tab.rename", "`": "last",
          "alt-h": "space.prev", "alt-l": "space.next", "alt-k": "agent.prev", "alt-j": "agent.next",
          "ctrl-alt-h": "tab.prev", "ctrl-alt-l": "tab.next",
          r: "unsupported", "ctrl-c": "unsupported", e: "unsupported", "[": "unsupported", "shift-z": "unsupported",
          "?": "app.help", "shift-/": "app.help", s: "app.settings", w: "mod.open:picker",
          "shift-n": "space.new", "shift-w": "space.rename", "shift-d": "space.close", "shift-x": "tab.close", x: "pane.close", b: "layout.toggle:sidebar",
        }[key];
        if (/^[1-9]$/.test(key)) command = `tab.select:${key}`;
        if (/^shift-[1-9]$/.test(key)) command = `space.select:${key.slice(-1)}`;
        if (/^alt-[1-9]$/.test(key)) command = `agent-${key.slice(-1)}`;
        // Open custom actions on demand; built-in commands work in every layout.
        if (command) {
          if (command.startsWith("split-") || command.startsWith("agent-") || command === "last") {
            run("mod.open", { name: `legacy-key-${command}` });
          } else if (command === "unsupported") {
            notify({ title: "Legacy shortcut unavailable", body: "This TUI action has no graphical equivalent.", level: "info" });
          } else {
            const [name, value] = command.split(":");
            run(name, value === undefined ? {} : name.endsWith("select") ? { index: Number(value) } : name === "layout.toggle" ? { id: value } : { name: value });
          }
        }
      });
  }
}
