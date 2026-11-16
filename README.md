# Spotify Playlist Export

Exports Spotify playlists (including private ones) whose names start with a given prefix
to **CSV** and **TXT** tracklists. These files can be imported with **TuneMyMusic** or
**Soundiiz** into Deezer, Tidal, Apple Music, YouTube Music and others, or shared as
plain tracklists.

- One Python script, standard library only: no `pip install`, no virtualenv
- Logs in through your browser (OAuth PKCE): only a Client ID is needed, no secret
- Exports ISRC codes, so the target service matches the exact recording

---

## Contents

1. [Requirements](#1-requirements)
2. [One-time setup](#2-one-time-setup)
3. [Usage](#3-usage)
4. [Output files](#4-output-files)
5. [Importing into other services](#5-importing-into-other-services)
6. [Troubleshooting](#6-troubleshooting)
7. [How it works](#7-how-it-works)

---

## 1. Requirements

| What | Notes |
|---|---|
| Python 3.8+ | Check with `python3 --version`. On macOS, install it with `xcode-select --install` or `brew install python` if it's missing. |
| A Spotify account | The same account that owns or follows the playlists. |
| A Spotify developer app | Free; see below. Gives you the **Client ID**. |
| A web browser | Used once to log in to Spotify. |
| Free port `8888` | The script briefly listens on `127.0.0.1:8888` to receive the login callback. |

---

## 2. One-time setup

### 2.1 Create the Spotify developer app

1. Open <https://developer.spotify.com/dashboard> and log in with your Spotify account.
   Accept the developer terms (you may have to verify your email address first).
2. Click **Create app** and fill in:

   | Field | Value |
   |---|---|
   | App name | anything, e.g. `Playlist Export` |
   | App description | anything |
   | Redirect URI | `http://127.0.0.1:8888/callback`, then click **Add** |
   | APIs used | tick **Web API** |

   > The redirect URI must match **exactly**. Spotify no longer accepts `localhost`;
   > it has to be `127.0.0.1`.

3. Accept the terms and click **Save**.
4. Open the app, go to **Settings** and copy the **Client ID** (32 characters, `0-9` and `a-f`).
   You do **not** need the Client Secret.

The app stays in *Development mode*. That's fine: the app owner can always use it with
their own account.

### 2.2 Store the Client ID

The script reads the Client ID from the environment variable `SPOTIFY_CLIENT_ID`
(or from `--client-id`).

**Option A: just for the current terminal window**

```sh
export SPOTIFY_CLIENT_ID=0123456789abcdef0123456789abcdef   # your real ID
```

**Option B: permanently (recommended)**

Add it to your shell profile so every new terminal has it:

```sh
echo 'export SPOTIFY_CLIENT_ID=0123456789abcdef0123456789abcdef' >> ~/.zshrc
source ~/.zshrc
```

Check that it's set:

```sh
echo "[$SPOTIFY_CLIENT_ID]"    # should print [ + 32 characters + ]
```

> The Client ID isn't a secret, but don't commit `.cache/token.json`: it holds
> your login token.

### 2.3 First login

```sh
git clone git@github.com:mtfinding/spotify-playlist-export.git
cd spotify-playlist-export
python3 spotify_export.py --list
```

Your browser opens the Spotify consent page. Approve it, and the tab shows
*"Login OK - you can close this tab."* The token is saved to `.cache/token.json` and
refreshed automatically, so you only log in once.

---

## 3. Usage

```sh
cd spotify-playlist-export

python3 spotify_export.py --list                # list playlists matching "30 - "
python3 spotify_export.py                       # export them to ./output
python3 spotify_export.py --prefix "Party"      # use a different name prefix
python3 spotify_export.py --prefix ""           # export ALL your playlists
python3 spotify_export.py --out ~/Desktop/export
python3 spotify_export.py --from-json output/raw/playlists.json   # rebuild files offline
python3 spotify_export.py --logout              # delete the saved login
```

| Option | Default | Description |
|---|---|---|
| `--prefix TEXT` | `"30 - "` | Only playlists whose name starts with this (case-sensitive). |
| `--client-id ID` | `$SPOTIFY_CLIENT_ID` | Spotify app Client ID. |
| `--out DIR` | `./output` | Where the files are written. Existing files are overwritten. |
| `--list` | | Only print the matching playlists and their IDs. |
| `--from-json FILE` | | Skip Spotify; regenerate CSV/TXT from a previous `raw/playlists.json`. |
| `--logout` | | Delete `.cache/token.json`. The next run logs in again. |

"My playlists" means everything in your library: playlists you created **and**
playlists you follow.

---

## 4. Output files

```
output/
├── all_playlists.csv      every track of every playlist, with a "Playlist" column
├── csv/
│   └── <playlist>.csv     one file per playlist
├── txt/
│   └── <playlist>.txt     one "Artist - Title" per line
└── raw/
    └── playlists.json     raw export (input for --from-json)
```

**CSV columns:** `Title, Artist, Album, ISRC, Duration, Spotify URL`
(`all_playlists.csv` has an extra `Playlist` column first). The files are UTF-8,
comma-separated, and multiple artists are joined with `, `.

**File names:** characters that aren't allowed in file names (`/ \ : * ? " < > |`) become `_`
(e.g. `30 - ???` → `30 - ___.csv`). macOS treats `Mystisch` and `mystisch` as the
same file name, so a second playlist that differs only in case gets a ` (2)` suffix.

**Not exported:** tracks that have been removed from Spotify. **Local files**
(tracks you added from your own computer) are exported, but they have no ISRC and
can't be matched by streaming services. The script prints how many each playlist has.

---

## 5. Importing into other services

### TuneMyMusic: <https://www.tunemymusic.com>

1. Click **Let's start** and choose **Upload file** as the source.
2. Upload `all_playlists.csv`. The `Playlist` column keeps the playlists separate.
   Alternatively, upload single files from `csv/`, or choose **Free text** and paste a `.txt`.
3. Choose the destination (Tidal, Deezer, Apple Music, ...), log in, and start the transfer.

### Soundiiz: <https://soundiiz.com>

1. Go to **Import playlist**, then **From file** (CSV) or **From plain text** (TXT).
2. If asked, map the columns: Title, Artist, Album, ISRC.
3. Choose the target service and confirm.

**Tips**

- Free tiers of both services limit how many tracks or playlists you can transfer at once.
- ISRC matching is the most exact. The TXT import matches by name only.
- **DJ software:** rekordbox, Serato and Traktor can stream from **Tidal** (also Beatport
  and SoundCloud), but not from Spotify. Importing into Tidal makes the playlists usable
  in the DJ software directly.
- To share tracklists that people only need to read, the `txt/` files are enough.

---

## 6. Troubleshooting

| Problem | Cause / fix |
|---|---|
| `Missing Client ID` | `SPOTIFY_CLIENT_ID` isn't set in this terminal. See [2.2](#22-store-the-client-id). |
| `Client ID 'your_client_id' doesn't look right` | A placeholder or a wrong value was copied. Paste the real 32-character Client ID from the app's **Settings** page, not the Client Secret. |
| Browser shows **INVALID_CLIENT: Invalid client** | The ID doesn't belong to any app: it was mistyped, or the app was deleted. Copy it again from the dashboard. |
| Browser shows **INVALID_CLIENT: Invalid redirect URI** | The app's Redirect URI must be exactly `http://127.0.0.1:8888/callback`. Edit it under **Settings**, then **Save**. |
| `OSError: [Errno 48] Address already in use` | Something else is using port 8888 (often a previous run that's still waiting). Close it, or run `lsof -i :8888` to find it. |
| Browser doesn't open | Copy the URL printed in the terminal into a browser manually. |
| `Token request failed (400) ... invalid_grant` | The saved login expired or was revoked. Run `--logout` and log in again. |
| `HTTP Error 403` while fetching | In Development mode, only the app owner and users added under **User Management** in the dashboard can use the app. Log in with the owner account or add the user there. |
| `rate limited, waiting Ns...` | Normal for large libraries. The script waits and retries automatically. |
| Playlist missing from `--list` | Check the exact prefix: matching is case-sensitive, and the default includes the space after the dash (`"30 - "`). |

To revoke the app's access entirely, go to Spotify **Account → Manage apps** and remove it.

---

## 7. How it works

1. **Login (Authorization Code + PKCE).** The script opens the Spotify authorize URL with
   the read-only scopes `playlist-read-private` and `playlist-read-collaborative`. It
   receives the callback on `127.0.0.1:8888` and exchanges the code for a token. The token
   is stored in `.cache/token.json` (permissions `600`) and refreshed automatically when it expires.
2. **Fetch.** It calls `GET /v1/me/playlists` (paginated), filters by name prefix, then
   calls `GET /v1/playlists/{id}/items`, falling back to `/tracks` on older API versions.
3. **Convert.** It writes `raw/playlists.json`, then the CSV and TXT files.
   `--from-json` reruns only this step.

The script only **reads** your Spotify data and never changes your playlists.

### Files in this folder

| File | Purpose |
|---|---|
| `spotify_export.py` | The exporter/converter |
| `README.md` | This file |
| `.cache/token.json` | Saved login (created on first run; private, don't share) |
| `output/` | Export results (created on run) |
