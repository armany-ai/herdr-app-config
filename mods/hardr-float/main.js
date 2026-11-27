// A terminal program in a float over the window, toggled like the lazygit float.
// Opened by the tab bar's buttons (mods/hardr-tabs) as a 1px runner window with props:
//   { app: "btop", argv: ["btop"], scope: "global" | "folder", keep: false }
// scope "folder": one copy per project (the focused pane's repo, else its folder), on the
// space's machine. scope "global": one copy, on this computer, started in the home folder.
// keep: the program stays running while its float is hidden (an editor with open files);
// without it the program ends when the float closes.
import { View, div } from "gpui-kit";
import { exec, hc, home, appHome, focused, spaces, panes, layout, theme, settings, run, openOverlay, closeOverlay, notify, props } from "herdr";

const MOD = "hardr-float";
const MEMORY = "__company_float_v1";
const LEASE_MS = 15000;

// Runner copies close after one toggle, so state that must outlive them lives here.
function memory() {
  return globalThis[MEMORY] ??= { dialog: null, lease: null };
}

async function claim(cx, owner) {
  const mem = memory();
  while (mem.lease && mem.lease.owner !== owner && Date.now() - mem.lease.at < LEASE_MS) await cx.sleep(15);
  mem.lease = { owner, at: Date.now() };
}

function release(owner) {
  const mem = memory();
  if (mem.lease?.owner === owner) mem.lease = null;
}

function coreError(result) {
  try { return JSON.parse(result.stderr).error.message; }
  catch { return result.stderr.trim() || `exit ${result.code}`; }
}

async function hcJSON(args, what) {
  const [command, ...rest] = args;
  const result = await hc([command, "--json", ...rest]);
  if (result.code !== 0) throw new Error(`${what}: ${coreError(result)}`);
  return JSON.parse(result.stdout);
}

// The live terminal this mod started for that program and folder, if any.
async function findInstance(spec, target) {
  const data = await hcJSON(["ls", "--label", `herdr.mod=${MOD}`], "List float terminals");
  for (const t of data.terminals ?? []) {
    if (t.state !== "live") continue;
    try {
      const labels = (await hcJSON(["get", t.address], "Read terminal")).labels ?? {};
      if (labels[`${MOD}.app`] === spec.app && labels[`${MOD}.dir`] === target.dir) return t.address;
    } catch { /* gone meanwhile */ }
  }
  return null;
}

// Where the program runs: its folder, and the machine for a per-project one.
// `pane`: the pane the person was in. While a float is open the keyboard is in its terminal,
// so focused() describes that terminal, not the pane under it.
async function locate(spec, pane) {
  if (spec.scope !== "folder") return { dir: home(), machine: null };
  const under = pane ? panes().find((p) => p.pane === pane) : null;
  const now = focused();
  const space = spaces().find((s) => s.id === now?.space);
  const machine = space?.machine ?? null;
  const cwd = (under ? under.cwd : now?.cwd) ?? space?.folder ?? null;
  if (!cwd) return { dir: home(), machine: null };
  try {
    const git = await exec("git", ["-C", cwd, "rev-parse", "--show-toplevel"], { on: machine });
    const root = git.code === 0 ? git.stdout.trim().split(/\r?\n/)[0] : "";
    return { dir: root || cwd, machine };
  } catch {
    return { dir: cwd, machine };
  }
}

async function start(spec, target) {
  const argv = spec.argv.map((a) => (a === "~" || a.startsWith("~/") ? home() + a.slice(1) : a));
  const result = await hc([
    "run", "--json", "--bg", "--rm", "--no-parent",
    ...(target.machine ? ["--on", target.machine] : []),
    "--cwd", target.dir,
    "--label", `herdr.mod=${MOD}`,
    "--label", `${MOD}.app=${spec.app}`,
    "--label", `${MOD}.dir=${target.dir}`,
    "--", ...argv,
  ]);
  if (result.code !== 0) throw new Error(`${argv[0]} did not start: ${coreError(result)}`);
  return JSON.parse(result.stdout).address;
}

function hide(dialog) {
  memory().dialog = null;
  closeOverlay(dialog.overlay); // its sentinel's close() ends a program that isn't kept
  if (dialog.previousPane) run("pane.focus", { pane: dialog.previousPane });
}

// The float's own glass: the shown layout's pane frame (its tint, corner light, border and
// radius, so it follows Kvantum and the light look), at a fixed strength instead of the Look
// popover's transparency.
const GLASS_ALPHA = 0.5;      // how solid the tint is: 0.5 is 50% see-through
const SHEEN_RATIO = 0.78;     // the lit corner is thinner than the body, as on the panes

function paneFrame(node) {
  if (node?.content?.pane) return node.content.pane;
  for (const child of node?.children ?? []) {
    const found = paneFrame(child);
    if (found) return found;
  }
  return null;
}

const rgb = (c) => (/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(c ?? "") ? c.slice(0, 7) : null);
const alpha = (a) => Math.round(Math.max(0, Math.min(1, a)) * 255).toString(16).padStart(2, "0");

function glass() {
  const pane = paneFrame(layout()) ?? {};
  const t = theme();
  const stops = pane.background?.gradient ?? [];
  const body = rgb(stops[1]) ?? rgb(stops[0]) ?? rgb(pane.background) ?? rgb(t.background) ?? "#1e1e2e";
  const lit = rgb(stops[0]) ?? body;
  return {
    body,
    gradient: (a) => ({ gradient: [lit + alpha(a * SHEEN_RATIO), body + alpha(a)], angle: pane.background?.angle ?? 160 }),
    border: pane.border ?? { width: 1, color: "border" },
    radius: pane.radius ?? 12,
  };
}

// What the float frosts. The desktop behind the window is blurred by the compositor, but under
// a float is the app itself, which nothing blurs: so this takes a picture of the window as it is
// now, blurs the part the float will cover and hands it over as the float's backing. It is a
// still: what moves under an open float doesn't show. A layout node doesn't clip its picture to
// its radius, so the picture gets the float's rounded corners itself. Resolves with a path in
// the app's folder, or null when the picture can't be made (no ImageMagick, no frame yet).
const SHARE = 0.9;   // the float's share of the window, each way
const BACKDROP = String.raw`
dir=$1 name=$2 flat=$3 share=$4 radius=$5 units=$6
mkdir -p "$dir" || exit 1
rm -f "$dir"/hardr-float-*.png
shot="$dir/.hardr-float-shot.png"
herdr-app shot "$shot" >/dev/null || exit 1
set -- $(magick identify -format '%w %h' "$shot")
cw=$(($1 * share / 1000)) ch=$(($2 * share / 1000))   # the part under the float
sw=$((cw / 8)) sh=$((ch / 8))                         # blurred small: cheap, and soft once scaled up
ow=$((cw / 2)) oh=$((ch / 2))                         # the picture: half size keeps its corners crisp
[ "$units" -gt 0 ] || units=$cw                       # the float's width in layout px, else 1:1
r=$((radius * ow / units))
magick "$shot" -gravity center -crop "$cw"x"$ch"+0+0 +repage -resize "$sw"x"$sh"! \
  -background "$flat" -alpha remove -alpha off -blur 0x3 -resize "$ow"x"$oh"! \
  \( -size "$ow"x"$oh" xc:black -fill white -draw "roundrectangle 0,0 $((ow - 1)),$((oh - 1)) $r,$r" \) \
  -alpha off -compose CopyOpacity -composite "$dir/$name"
status=$?
rm -f "$shot"
exit $status
`;

async function backdrop(look, cx) {
  // The runner covers the window, so its size is the window's: wait a moment for its first layout.
  const mem = memory();
  for (let i = 0; i < 10 && !mem.window; i++) await cx.sleep(15);
  const units = mem.window ? Math.round(SHARE * mem.window.width / (settings().zoom || 1)) : 0;
  const name = `hardr-float-${Date.now()}.png`;
  try {
    const made = await exec("sh", ["-c", BACKDROP, "sh", `${appHome()}/backgrounds`, name, look.body,
      String(Math.round(SHARE * 1000)), String(Math.round(look.radius)), String(units)], { timeout: 5000 });
    return made.code === 0 ? `backgrounds/${name}` : null;
  } catch {
    return null;
  }
}

function show(spec, address, previousPane, look, image) {
  // Two layers: the blurred picture, then the pane tint over it. Without the picture the tint
  // goes nearly solid, or the app's own text would read through the float's.
  const card = {
    type: "column", background: look.gradient(image ? GLASS_ALPHA : 0.94), border: look.border, radius: look.radius,
    children: [
      { type: "block", size: { px: 0 }, content: { mod: MOD, props: { role: "sentinel", terminal: address, keep: Boolean(spec.keep) } } },
      { type: "block", content: { terminal: address } },
    ],
  };
  const overlay = openOverlay({
    kind: "dialog", width: SHARE, height: SHARE, frame: "none",
    layout: image ? { type: "column", background: { image, fit: "cover" }, children: [card] } : card,
  });
  memory().dialog = { overlay, app: spec.app, terminal: address, previousPane, image };
}

async function toggle(spec, cx) {
  const open = memory().dialog;
  const pane = open ? open.previousPane : focused()?.pane ?? null;
  if (open) {
    hide(open);
    if (open.app === spec.app) return; // the same button again: just close
  }
  const look = glass();
  // Another float was open: the window under it is the same, so its picture serves again.
  const [address, image] = await Promise.all([
    locate(spec, pane).then(async (target) => (await findInstance(spec, target)) ?? (await start(spec, target))),
    open ? open.image : backdrop(look, cx),
  ]);
  show(spec, address, pane, look, image);
}

async function runToggle(spec, owner, cx) {
  try {
    await claim(cx, owner);
    await toggle(spec, cx);
  } catch (error) {
    notify({ title: spec.app ?? "Float", body: String(error?.message ?? error), level: "error" });
  } finally {
    release(owner);
    closeOverlay(owner);
  }
}

export default class Float extends View {
  init(_props, cx) {
    this.copy = props() ?? {};
    if (this.copy.role === "sentinel") return;
    const owner = this.copy.overlay;
    if (owner && this.copy.app && Array.isArray(this.copy.argv)) cx.spawn((cx) => runToggle(this.copy, owner, cx));
    else if (owner) closeOverlay(owner);
  }

  // The dialog also closes on a click outside, Esc or a layout switch; this keeps the toggle
  // state true and ends a program that doesn't stay running while hidden.
  async close() {
    if (this.copy.role !== "sentinel") {
      if (this.copy.overlay) release(this.copy.overlay);
      return;
    }
    const mem = memory();
    if (mem.dialog?.overlay === this.copy.overlay) mem.dialog = null;
    if (!this.copy.keep) await exec("hc", ["kill", this.copy.terminal]);
  }

  render() {
    if (this.copy.role === "sentinel") return div();
    // The runner: an empty window as big as the app's, which is how the float learns that size.
    return div().id("float-runner").size_full().on_size_change((size) => { memory().window = size; });
  }
}
