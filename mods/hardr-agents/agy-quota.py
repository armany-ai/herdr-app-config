#!/usr/bin/env python3
# pixel-hq AGY quota reader for Pixel HQ. Prints a single line of JSON: {"quota": <0-100 or null>} where quota is the share of the plan's
# quota window still left, the tightest bucket across the models Antigravity actually offers (chat_/tab_ plumbing skipped).
# Talks to the same Google endpoint the agy CLI uses. Refreshes the CLI's OAuth token itself when it aged out.
# No credentials of Pixel HQ's own: the public OAuth pair is read from the `agy` binary installed on this machine (cached in the user's
# cache dir for later runs). Honors AGY_HOME for a non-standard CLI install (default ~/.gemini/antigravity-cli).
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from urllib import parse, request

AGY_HOME = os.environ.get("AGY_HOME") or os.path.join(os.path.expanduser("~"), ".gemini", "antigravity-cli")
TOKEN_FILE = os.path.join(AGY_HOME, "antigravity-oauth-token")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"), "pixel-hq")
PAIR_CACHE = os.path.join(CACHE_DIR, "agy-oauth.json")
TIMEOUT = 10

ID_RE = re.compile(rb"[0-9]+-[0-9a-z]{32}\.apps\.googleusercontent\.com")
SECRET_RE = re.compile(rb"GOCSPX-[A-Za-z0-9_-]{28}")


def agy_binary():
    which = shutil.which("agy")
    if which:
        return which
    candidates = [
        os.path.join(AGY_HOME, "bin", "agy.exe" if os.name == "nt" else "agy"),
        os.path.join(os.path.expanduser("~"), ".local", "bin", "agy.exe" if os.name == "nt" else "agy"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def pair_candidates():
    try:
        with open(PAIR_CACHE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        if cached.get("client_id") and cached.get("client_secret"):
            return [(cached["client_id"], cached["client_secret"])]
    except Exception:
        pass
    binary = agy_binary()
    if not binary:
        return []
    try:
        with open(binary, "rb") as f:
            data = f.read()
    except Exception:
        return []
    ids = list(dict.fromkeys(m.decode() for m in ID_RE.findall(data)))
    secrets = list(dict.fromkeys(m.decode() for m in SECRET_RE.findall(data)))
    return [(i, s) for i in ids for s in secrets]


def save_pair(pair):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(PAIR_CACHE, "w", encoding="utf-8") as f:
            json.dump({"client_id": pair[0], "client_secret": pair[1]}, f)
        if os.name != "nt":
            try:
                os.chmod(PAIR_CACHE, 0o600)
            except OSError:
                pass
    except Exception:
        pass


def load_token():
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        token_data = json.load(f)
    return token_data, token_data.get("token") or {}


def refresh(pair, refresh_token):
    payload = parse.urlencode({
        "client_id": pair[0],
        "client_secret": pair[1],
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = request.Request("https://oauth2.googleapis.com/token", data=payload)
    try:
        with request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def get_valid_token():
    token_data, token = load_token()
    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    expiry_str = token.get("expiry")

    is_expired = False
    if expiry_str:
        try:
            expiry_dt = datetime.fromisoformat(expiry_str)
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)
            is_expired = datetime.now(timezone.utc) >= expiry_dt
        except Exception:
            pass

    if is_expired and refresh_token:
        refreshed = None
        winner = None
        for pair in pair_candidates():
            res = refresh(pair, refresh_token)
            if res and res.get("access_token"):
                refreshed, winner = res, pair
                break
        if not refreshed:
            sys.exit(3)
        access_token = refreshed["access_token"]
        token["access_token"] = access_token
        if refreshed.get("expires_in"):
            token["expires_in"] = refreshed["expires_in"]
            token["expiry"] = datetime.now().astimezone().replace(microsecond=0).isoformat()
        token_data["token"] = token
        try:
            with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                json.dump(token_data, f, indent=2)
        except OSError:
            pass
        if winner:
            save_pair(winner)

    if not access_token:
        sys.exit(3)
    return access_token


def call_api(path, token, body):
    req = request.Request(
        f"https://cloudcode-pa.googleapis.com/v1internal:{path}",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "antigravity",
        },
    )
    with request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode())


def main():
    try:
        token = get_valid_token()
    except FileNotFoundError:
        sys.exit(3)
    except Exception:
        sys.exit(3)

    try:
        assist = call_api("loadCodeAssist", token, {
            "metadata": {
                "ideType": "ANTIGRAVITY",
                "platform": "PLATFORM_UNSPECIFIED",
                "pluginType": "GEMINI",
            },
        })
    except Exception:
        sys.exit(4)

    project_id = assist.get("cloudaicompanionProject", "aicode-consumers")
    if isinstance(project_id, dict):
        project_id = project_id.get("id", "aicode-consumers")

    try:
        models_data = call_api("fetchAvailableModels", token, {"project": project_id})
    except Exception:
        sys.exit(4)

    remaining = []
    seen = set()
    for info in (models_data.get("models") or {}).values():
        name = info.get("displayName") or ""
        if name in seen or name.startswith("chat_") or name.startswith("tab_"):
            continue
        seen.add(name)
        quota = info.get("quotaInfo") or {}
        fraction = quota.get("remainingFraction")
        if isinstance(fraction, (int, float)):
            remaining.append(fraction)

    print(json.dumps({"quota": int(round(min(remaining) * 100)) if remaining else None}))


if __name__ == "__main__":
    main()
