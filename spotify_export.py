#!/usr/bin/env python3
"""Export Spotify playlists to CSV/TXT files for TuneMyMusic, Soundiiz & co.

Stdlib only. Uses the Spotify Web API with the Authorization Code + PKCE flow,
so only a Client ID is needed (no client secret).

Usage:
    export SPOTIFY_CLIENT_ID=<your client id>
    python3 spotify_export.py                     # export playlists starting with "30 - "
    python3 spotify_export.py --prefix "Party"    # different prefix
    python3 spotify_export.py --list              # only list matching playlists
    python3 spotify_export.py --from-json output/raw/playlists.json   # re-convert offline
"""

import argparse
import base64
import csv
import hashlib
import http.server
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API = "https://api.spotify.com/v1"
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "playlist-read-private playlist-read-collaborative"

HERE = Path(__file__).resolve().parent
TOKEN_FILE = HERE / ".cache" / "token.json"

CSV_FIELDS = ["Title", "Artist", "Album", "ISRC", "Duration", "Spotify URL"]


# --- auth ------------------------------------------------------------------

def _post_form(url, data):
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"Token request failed ({e.code}): {e.read().decode(errors='replace')}")


def _save_token(tok):
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tok))
    os.chmod(TOKEN_FILE, 0o600)
    return tok


def _browser_login(client_id):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)

    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "scope": SCOPES,
        "state": state,
    })

    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if urllib.parse.urlparse(self.path).path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in q.items()})
            ok = "code" in result and result.get("state") == state
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Login OK - you can close this tab." if ok else f"Login failed: {result}"
            self.wfile.write(f"<h2>{msg}</h2>".encode())

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 8888), Handler)
    print("Opening browser for Spotify login...")
    print(f"If it doesn't open, visit:\n{url}\n")
    webbrowser.open(url)
    while "code" not in result and "error" not in result:
        server.handle_request()
    server.server_close()

    if "error" in result:
        sys.exit(f"Spotify login failed: {result['error']}")
    if result.get("state") != state:
        sys.exit("Spotify login failed: state mismatch")

    return _save_token(_post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": result["code"],
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": verifier,
    }))


def _refresh(client_id, tok):
    new = _post_form(TOKEN_URL, {
        "grant_type": "refresh_token",
        "refresh_token": tok["refresh_token"],
        "client_id": client_id,
    })
    new.setdefault("refresh_token", tok["refresh_token"])
    return _save_token(new)


class Spotify:
    def __init__(self, client_id):
        self.client_id = client_id
        self.tok = json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else None
        if not self.tok:
            self.tok = _browser_login(client_id)
        elif time.time() > self.tok.get("expires_at", 0):
            self.tok = _refresh(client_id, self.tok)

    def get(self, url, params=None, _retried=False):
        if not url.startswith("http"):
            url = API + url
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.tok['access_token']}"}
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", "5"))
                print(f"  rate limited, waiting {wait}s...")
                time.sleep(wait)
                return self.get(url, _retried=_retried)
            if e.code == 401 and not _retried:
                self.tok = _refresh(self.client_id, self.tok)
                return self.get(url, _retried=True)
            raise

    def paginate(self, url, params=None):
        page = self.get(url, params)
        while page:
            yield from page.get("items", [])
            page = self.get(page["next"]) if page.get("next") else None


# --- export ----------------------------------------------------------------

def fetch_playlists(sp, prefix):
    mine = [p for p in sp.paginate("/me/playlists", {"limit": 50}) if p]
    return [p for p in mine if p.get("name", "").startswith(prefix)]


def fetch_tracks(sp, playlist_id):
    # Newer API versions expose /items; older ones /tracks. Try both.
    params = {"limit": 100, "additional_types": "track,episode"}
    try:
        entries = list(sp.paginate(f"/playlists/{playlist_id}/items", params))
    except urllib.error.HTTPError as e:
        if e.code not in (403, 404):
            raise
        entries = list(sp.paginate(f"/playlists/{playlist_id}/tracks", params))

    tracks = []
    for entry in entries:
        item = entry.get("item") or entry.get("track")
        if not item:
            continue  # track removed from Spotify
        if item.get("type") == "episode":
            artists = (item.get("show") or {}).get("name", "")
            album = ""
        else:
            artists = ", ".join(a["name"] for a in item.get("artists", []) if a.get("name"))
            album = (item.get("album") or {}).get("name", "")
        tracks.append({
            "title": item.get("name", ""),
            "artist": artists,
            "album": album,
            "isrc": (item.get("external_ids") or {}).get("isrc", ""),
            "duration_ms": item.get("duration_ms") or 0,
            "url": (item.get("external_urls") or {}).get("spotify", ""),
            "is_local": bool(entry.get("is_local") or item.get("is_local")),
        })
    return tracks


# --- convert ---------------------------------------------------------------

def _fmt_duration(ms):
    s = round(ms / 1000)
    return f"{s // 60}:{s % 60:02d}"


def _safe_filename(name, used):
    base = re.sub(r'[/\\:*?"<>|]', "_", name).strip().rstrip(".") or "playlist"
    # macOS filesystems are case-insensitive: "Mystisch" and "mystisch" collide
    candidate, n = base, 2
    while candidate.lower() in used:
        candidate, n = f"{base} ({n})", n + 1
    used.add(candidate.lower())
    return candidate


def write_outputs(playlists, out_dir):
    csv_dir, txt_dir = out_dir / "csv", out_dir / "txt"
    csv_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)
    used = set()

    with open(out_dir / "all_playlists.csv", "w", newline="", encoding="utf-8") as f_all:
        all_writer = csv.writer(f_all)
        all_writer.writerow(["Playlist"] + CSV_FIELDS)

        for pl in playlists:
            fname = _safe_filename(pl["name"], used)
            with open(csv_dir / f"{fname}.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(CSV_FIELDS)
                for t in pl["tracks"]:
                    row = [t["title"], t["artist"], t["album"], t["isrc"],
                           _fmt_duration(t["duration_ms"]), t["url"]]
                    w.writerow(row)
                    all_writer.writerow([pl["name"].strip()] + row)

            # One "Artist - Title" per line: readable, and accepted as text import
            with open(txt_dir / f"{fname}.txt", "w", encoding="utf-8") as f:
                for t in pl["tracks"]:
                    f.write(f"{t['artist']} - {t['title']}\n")

            local = sum(t["is_local"] for t in pl["tracks"])
            note = f", {local} local file(s) - won't match on streaming services" if local else ""
            print(f"  {pl['name']!r}: {len(pl['tracks'])} tracks{note}")


# --- main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prefix", default="30 - ", help='playlist name prefix (default: "30 - ")')
    ap.add_argument("--client-id", default=os.environ.get("SPOTIFY_CLIENT_ID"))
    ap.add_argument("--out", type=Path, default=HERE / "output")
    ap.add_argument("--list", action="store_true", help="only list matching playlists")
    ap.add_argument("--from-json", type=Path, help="skip the API, convert a previous raw export")
    ap.add_argument("--logout", action="store_true", help="delete the cached login token")
    args = ap.parse_args()

    if args.logout:
        TOKEN_FILE.unlink(missing_ok=True)
        print("Token removed.")
        return

    if args.from_json:
        playlists = json.loads(args.from_json.read_text(encoding="utf-8"))
        print(f"Converting {len(playlists)} playlists from {args.from_json}")
        write_outputs(playlists, args.out)
        print(f"Done -> {args.out}")
        return

    if not args.client_id:
        sys.exit("Missing Client ID: set SPOTIFY_CLIENT_ID or pass --client-id (see README.md)")
    args.client_id = args.client_id.strip().strip("'\"")
    if not re.fullmatch(r"[0-9a-f]{32}", args.client_id):
        sys.exit(f"Client ID {args.client_id!r} doesn't look right: it should be 32 characters "
                 "(0-9, a-f), copied from the app's Settings page in the Spotify dashboard.")

    sp = Spotify(args.client_id)
    matches = fetch_playlists(sp, args.prefix)
    print(f"Found {len(matches)} playlists starting with {args.prefix!r}")
    if args.list:
        for p in matches:
            print(f"  {p['name']!r}  ({p['id']})")
        return

    playlists = []
    for i, p in enumerate(matches, 1):
        print(f"[{i}/{len(matches)}] {p['name']}")
        playlists.append({
            "name": p["name"],
            "id": p["id"],
            "url": (p.get("external_urls") or {}).get("spotify", ""),
            "tracks": fetch_tracks(sp, p["id"]),
        })

    raw = args.out / "raw" / "playlists.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps(playlists, ensure_ascii=False, indent=1), encoding="utf-8")

    print("Writing files:")
    write_outputs(playlists, args.out)
    print(f"Done -> {args.out}")


if __name__ == "__main__":
    main()
