import { View, div } from "gpui-kit";
import { openOverlay, closeOverlay, props } from "herdr";
export default class Shortcut extends View {
  init(_props, cx) {
    const owner = props()?.overlay;
    if (!owner) return;
    cx.spawn(() => {
      openOverlay({ mod: "legacy-keys", kind: "window", frame: "none", width: 1, height: 1, props: { command: "attention" } });
      closeOverlay(owner);
    });
  }
  render() { return div(); }
}
