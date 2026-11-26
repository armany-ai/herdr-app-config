#!/bin/sh
# Agent status line for Pixel HQ (Claude Code, Antigravity, and other compatible agents).
# The agent hands this script a JSON blob on stdin after every turn or status change;
# it tells Herdr how full the context is (labels agent.context / claude.context, 0-100),
# how much of the quota window is left (agent.quota / claude.quota, 0-100) and effort level (agent.effort / claude.effort)
# so the desk can show HP/SP bars, and prints a short status.
# Also clears the labels when the agent stops reporting them, so a stale number never outlives its source.
# Needs python3. Outside a Herdr terminal it only prints the status.
input=$(cat)
fields=$(printf '%s' "$input" | python3 -c '
import json, os, sys
try:
    d = json.load(sys.stdin)
    if not isinstance(d, dict):
        d = {}
except Exception:
    d = {}

def clean(v):
    if not isinstance(v, str):
        v = "" if v is None else str(v)
    out = []
    for ch in v:
        o = ord(ch)
        if o <= 31 or o == 127:
            continue
        out.append(ch)
    return "".join(out).replace("|", "·")

m = d.get("model")
model = ""
if isinstance(m, dict):
    model = clean(m.get("display_name") or m.get("name") or m.get("id") or m.get("title") or "")
elif isinstance(m, str):
    model = clean(m)

if not model:
    model = clean(d.get("model_name") or d.get("model_id") or d.get("current_model") or "")

if not model:
    try:
        tp = clean(d.get("transcript_path") or "")
        if tp and os.path.exists(tp):
            for line in open(tp, "r", encoding="utf-8"):
                if "\"model\":" in line:
                    try:
                        ev = json.loads(line)
                        mod = (ev.get("message") or {}).get("model") or ev.get("model") or (ev.get("payload") or {}).get("model")
                        if mod and isinstance(mod, str):
                            model = clean(mod)
                    except Exception: pass
    except Exception: pass

if not model and d:
    for sp in [os.path.expanduser("~/.claude/settings.json"), os.path.expanduser("~/.gemini/antigravity-cli/settings.json")]:
        try:
            if os.path.exists(sp):
                sdata = json.load(open(sp, "r", encoding="utf-8"))
                model = clean(sdata.get("model") or "")
                if model: break
        except Exception: pass

c = (d.get("context_window") if isinstance(d.get("context_window"), dict) else {}) or {}
p = c.get("used_percentage")
if p is None:
    used_in = c.get("total_input_tokens")
    used_out = c.get("total_output_tokens")
    size = c.get("context_window_size")
    if used_in is not None and size:
        used = (used_in or 0) + (used_out or 0)
        p = used * 100.0 / size
if p is None:
    # older Claude Code: estimate from the last assistant message in the transcript
    try:
        last = None
        for line in open(clean(d.get("transcript_path") or "") or "/nonexistent"):
            try:
                u = (json.loads(line).get("message") or {}).get("usage")
            except Exception:
                u = None
            if u:
                last = u
        if last:
            used = last.get("input_tokens", 0) + last.get("cache_read_input_tokens", 0) + last.get("cache_creation_input_tokens", 0)
            size = 1000000 if "1m" in clean((d.get("model") or {}).get("id", "") if isinstance(d.get("model"), dict) else "").lower() else 200000
            p = used * 100.0 / size
    except Exception:
        pass
pct = str(max(0, min(100, int(round(p))))) if isinstance(p, (int, float)) else ""

# Quota: Claude Code rate_limits or Antigravity quota
q_pct = None
rl = d.get("rate_limits") if isinstance(d.get("rate_limits"), dict) else {}
five = rl.get("five_hour") if isinstance(rl.get("five_hour"), dict) else {}
if isinstance(five.get("used_percentage"), (int, float)) and 0 <= five["used_percentage"] <= 100:
    q_pct = int(round(100 - five["used_percentage"]))
elif isinstance(d.get("quota"), dict):
    q_dict = d["quota"]
    g5h = q_dict.get("gemini-5h") or q_dict.get("3p-5h")
    if isinstance(g5h, dict) and "remaining_fraction" in g5h and isinstance(g5h["remaining_fraction"], (int, float)):
        q_pct = int(round(g5h["remaining_fraction"] * 100))

quota = str(max(0, min(100, q_pct))) if q_pct is not None else ""

eff = d.get("effort") if isinstance(d.get("effort"), dict) else {}
effort = clean(eff.get("level") or (m.get("effort") if isinstance(m, dict) else "") or "")
print(pct + "|" + model + "|" + quota + "|" + effort)
' 2>/dev/null)
pct=${fields%%\|*}; rest=${fields#*\|}; model=${rest%%\|*}; rest=${rest#*\|}; quota=${rest%%\|*}; effort=${rest#*\|}

if [ -n "$HC_TERMINAL_ID" ] && command -v hc >/dev/null 2>&1; then
  hc label "$HC_TERMINAL_ID" \
    "agent.context=$pct" "claude.context=$pct" "agy.context=$pct" \
    "agent.model=$model" "claude.model=$model" "agy.model=$model" \
    "agent.quota=$quota" "claude.quota=$quota" "agy.quota=$quota" \
    "agent.effort=$effort" "claude.effort=$effort" "agy.effort=$effort" >/dev/null 2>&1 &
fi
if [ -n "$pct" ]; then
  if [ -n "$quota" ]; then printf '%s · %s%% context · %s%% 5h left' "$model" "$pct" "$quota"; else printf '%s · %s%% context' "$model" "$pct"; fi
else printf '%s' "$model"
fi
