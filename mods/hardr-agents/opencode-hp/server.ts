// pixel-hq-opencode-hp v1
// Server part of the OpenCode HP plugin: a no-op. All the work lives in tui.tsx, which runs inside each TUI,
// where the terminal's own HC_TERMINAL_ID is visible. This entry exists so the server half does not report a
// missing entrypoint when it auto-discovers the directory.
export default {
  id: "pixel-hq-hp",
  async setup() {},
};
