import { PathBuilder, Background, div } from "gpui-kit";
import { shared, theme } from "herdr";

export const isP5 = () => shared("layout") === "persona5";

export function panelTheme() {
  const t = theme();
  return isP5() ? { ...t, background: "#170006", raised: "#39000b", selected: "#000000",
    foreground: "#ffffff", muted: "#e8cbd0", dim: "#bf98a1", border: "#64101e",
    hover: "#57000e", input: "#ff6975", accent: "#5ef2ff" } : t;
}

const RECT = [[0, 0], ["100%", 0], ["100%", "100%"], [0, "100%"]];
const SLAB = [[0, "8%"], ["97%", 0], ["100%", "92%"], ["2%", "100%"]];
const TAG = [["3%", 0], ["100%", "8%"], ["97%", "100%"], [0, "90%"]];
const path = (points, width = 0) => (width ? PathBuilder.stroke(width) : PathBuilder.fill()).add_polygon(points, true).build();
const paint = (points, color, width = 0) => globalThis.window.paint_path(path(points, width), color).absolute().inset_0();

export function p5Header(el) {
  if (!isP5()) return el;
  return el.relative().h(46).rounded(0).bg("#93000b").border_b(0).italic().font_weight(800)
    .child(paint(RECT, Background.pattern_slash("#00000030", 3, 14)));
}

export function titleTag(text) {
  return isP5()
    ? div().relative().px(10).py(4).flex_none()
      .child(paint(TAG, "#ffffff"))
      .child(div().relative().text_size(12).font_weight(900).italic().text_color("#000000").child(text.toUpperCase()))
    : div().font_semibold().child(text);
}

export function p5Card(el, selected) {
  if (!isP5()) return selected ? el.bg(theme().selected) : el;
  return el.relative().rounded(0).my(5).px(13).py(13)
    .when(selected, (e) => e
      .child(div().absolute().top(4).bottom(-4).left(5).right(-5).child(paint(SLAB, "#ff1a8c")))
      .child(div().absolute().top(-2).bottom(2).left(-3).right(3).child(paint(SLAB, "#00e5ff"))))
    .child(paint(SLAB, selected ? "#000000" : "#39000b"))
    .when(selected, (e) => e.child(paint(SLAB, "#ffffff", 1.5)));
}

export function p5Shell(el) {
  return isP5() ? el.rounded(0).border(0).border_l(2).border_color("#f2e6d6") : el;
}
