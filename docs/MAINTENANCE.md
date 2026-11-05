# Running and maintaining MediaTracker

This guide assumes you never change the app's features. It covers what you do need to do: install it once, keep it updated, and make sure the data is safe.

**Short version:** once a month, pull the new image and restart the container (2 minutes). Every few months, check that backups are being written and copied off the server. That's it.

---

## 1. What's running

| Piece | Where |
|---|---|
| The app | One container, `ghcr.io/duffduff99/mediatracker`. It listens on port **8080**, published on the host as 8080 unless you set `MT_PORT` |
| Your data | One file, `mediatracker.db`, in the container's `/data`. By default `/data` is a Docker volume named `mediatracker_mediatracker-data` |
| Nightly backups | `/data/backups/mediatracker-YYYY-MM-DD.db` (the last 14 are kept) |

There is no separate database server, cache or queue. If the container and its `/data` volume are fine, the app is fine.

## 2. First install

### 2.1 Deploy from Git in Dockhand

The repository's [`docker-compose.yml`](../docker-compose.yml) pulls the ready-made image that GitHub builds on every merge to `main`. The image is public, so no registry login is needed. Your server doesn't build anything; Dockhand only reads the compose file from Git.

1. In Dockhand, create a new stack from a **Git repository**:
   - Repository: `https://github.com/duffduff99/MediaTracker.git` (public, so no credentials)
   - Branch: `main`
   - Compose file path: `docker-compose.yml`. Dockhand's default is `compose.yaml`, so change it.
   - Stack name: `mediatracker`
2. Add **stack variables** (all optional):

   | Variable | Example | Default |
   |---|---|---|
   | `TZ` | `America/Chicago` | `UTC` |
   | `MT_PORT` | `8080` | `8080`. The host port your reverse proxy points at |
   | `MT_DATA` | `/srv/mediatracker/data` | a Docker volume (see below) |
   | `MT_ADMIN_PASSWORD` | | a random one printed in the log |

3. Deploy.

**Where the data lives (`MT_DATA`).** Leave it unset to use a Docker volume. Docker sets the right permissions, and the volume lives with your other Docker data in `/var/lib/docker/volumes/`, so your existing Docker backup covers it. If you'd rather have a plain folder, set `MT_DATA` to an **absolute** path and create it first, owned by uid 1000. The app deliberately doesn't run as root, so it can't fix a root-owned folder itself:

```bash
sudo mkdir -p /srv/mediatracker/data && sudo chown 1000:1000 /srv/mediatracker/data
```

Don't use a relative path like `./data` in a Git stack: it would sit inside Dockhand's copy of the repository, which a re-sync can replace.

**Updates.** The compose file sets `pull_policy: always`, so every redeploy pulls the newest image. You can also turn on Dockhand's auto-sync or a GitHub webhook to redeploy whenever `main` changes. That's safe: the data is in the volume, not the container.

**Without Dockhand:** `docker compose up -d` in a checkout of the repo works the same way, and `MT_*` variables can go in a `.env` file next to it. To build the image on the server instead of pulling it, replace `image:` with `build: .`.

### 2.2 Get the admin password

On first start the app creates a user called `admin` and prints a random password in the container log:

```
================================================================
  First start: created admin user 'admin'
  Password: xxxxxxxxxxxxxxxx
```

In Dockhand, open the container's logs. From a shell, run `docker logs mediatracker`. Sign in, then change the password under **Settings → My account**. (Or set `MT_ADMIN_PASSWORD` in the compose file *before* the first start.)

### 2.3 Reverse proxy and HTTPS

HTTPS is required for the **barcode scanner** and for **installing the app on your phone**. Browsers block both on plain `http://`. Point your existing reverse proxy at `http://<docker-host>:8080`:

- Use a certificate your phone already trusts (the same setup as your other internal services).
- Pass the usual `X-Forwarded-For` and `X-Forwarded-Proto` headers. Most proxies do this by default. The app uses them to mark sign-in cookies as secure and to rate-limit failed sign-ins per device.
- Allow uploads of at least 20 MB (only the Jira import uses this). On **nginx / Nginx Proxy Manager**, set `client_max_body_size 20m;`, because the default of 1 MB is too small. Traefik and Caddy have no small limit by default.

Example nginx location:

```nginx
location / {
    proxy_pass http://docker-host:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 20m;
}
```

### 2.4 Import from Jira

See [IMPORT.md](IMPORT.md). In short: **Settings → Import & export → Import from Jira** → choose the CSV → **Preview** → read the report → **Import**.

### 2.5 Add the household and install on phones

- **Settings → Users** → add each person.
  - **Viewer** can search, browse and export.
  - **Editor** can also add, edit and delete.
  - **Admin** can also manage columns, media types, users and the import.
- On each phone, connect to WireGuard and open the app's HTTPS address. Then:
  - **iPhone:** Share → **Add to Home Screen**.
  - **Android (Chrome):** ⋮ → **Install app**.

### 2.6 Barcode lookup (optional)

When you scan a barcode on the Add screen, the app can fill in the title, year, artist and some columns from free online databases. It works out of the box for music (MusicBrainz) and gives basic product names for discs and games (UPCitemdb). Two free keys make it better:

- **TMDB API key**: proper movie and TV titles and the original release year. Create a free account at themoviedb.org, then go to Settings → API. Either the "API Key" or the "API Read Access Token" works.
- **Discogs personal access token**: a second source for records, cassettes and CDs. Create a free account, then go to Settings → Developers → Generate new token.

Paste them in **Settings → Barcode lookup** (admins only) and press **Test**. That page also has a **Try a barcode** box that shows what each source answered, and a switch to turn lookups off entirely.

**Firewall:** the server, not your phone, makes these requests over HTTPS (port 443) to:

| Host | Used for |
|---|---|
| `musicbrainz.org` | Music (no key) |
| `api.discogs.com` | Music (with a Discogs token) |
| `api.upcitemdb.com` | Product names for movies, TV and games (free tier, about 100 lookups/day) |
| `api.themoviedb.org` | Movie/TV titles and years (with a TMDB key) |

Results are saved in the database (found: 90 days, not found: 7 days), so scanning the same item again doesn't use up the daily UPCitemdb allowance. The keys are stored in the database too, which means they're in your backups. They're free keys, but treat backups accordingly.

### 2.7 Plex sync (optional)

Plex can keep your **Digital** items up to date. Each movie and each TV season in Plex becomes a Digital copy, linked to the discs you own of the same title. Titles removed from Plex go to the trash.

1. **Settings → Plex**: enter the Plex address as the MediaTracker server sees it (e.g. `http://192.168.1.20:32400`) and your **Plex token**. To find the token, open Plex Web, go to any movie → ⋯ → **Get Info** → **View XML**, and copy the value after `X-Plex-Token=` in that page's address. Press **Save**, then **Test connection**.
2. Tick the Movie and TV libraries to sync, and check that **Plex manages this format** says Digital.
3. Press **Preview** and read what it would change. The first sync takes over your existing Digital items: matching ones are kept, and the rest go to the trash, restorable for 30 days.
4. Press **Sync now**. After the first sync it runs every hour; there's a switch to turn that off.

Notes:
- **Network:** the MediaTracker container must reach the Plex server on port 32400. If Plex's **Secure connections** setting is "Required", plain `http://` is refused. Use the server's `https://…plex.direct:32400` address instead, or set it to "Preferred".
- **TV seasons** are named "Show - Season N", the same way as your Blu-ray seasons, so they link. Specials (season 0) are skipped.
- **Adding Digital items by hand** isn't useful once Plex manages Digital: the next sync removes them. Add the title in Plex instead.
- **Safety:** if Plex returns nothing (e.g. it's down), nothing changes. An automatic sync won't remove more than a quarter of the Digital items at once; the last-sync line says so if that happens. A manual **Sync now** applies it.

## 3. Routine maintenance

### Monthly: update (≈ 2 minutes)

Updates contain security fixes for Python, the base image and the libraries the app uses, even when nothing visible changes.

1. In Dockhand, **redeploy** the MediaTracker stack. `pull_policy: always` fetches the newest image. If auto-sync or a webhook is on, this happens by itself when `main` changes. From a shell:
   ```bash
   docker compose pull
   docker compose up -d
   ```
2. Open the app and check that it loads and search works.

Database changes are applied automatically when the new version starts, and a backup from that night already exists. To go back to a previous version, see §5.

New images appear when code is merged to `main` on GitHub. Dependabot opens monthly pull requests with library updates. The **Test and build image** check runs the automated tests on each one; if it's green, merging it publishes a new image.

### Every few months: check backups

1. Look in `/data/backups/`, using Dockhand's volume browser or `docker exec mediatracker ls -l /data/backups`. You should see one file per night, up to 14.
2. Make sure your existing Docker backup includes the volume (or your `MT_DATA` folder), and that copies leave the server (to a NAS or offsite).
3. Once in a while, do a test restore (§5) into a scratch container. A backup you've never restored is a guess.

**Why the nightly copies matter:** copying `mediatracker.db` while the app is writing can produce a damaged copy. The files in `/data/backups/` are made with SQLite's own backup function, so they are always consistent. Your volume backup will pick them up.

You can also download a backup at any time: **Settings → Import & export → Download backup**.

### Yearly: tidy up

- In **Settings → Users**, remove anyone who no longer needs access.
- Look through the **Trash**. Items are deleted permanently after 30 days anyway.

## 4. Settings you can change (environment variables)

Set these as Dockhand stack variables, or in a `.env` file next to the compose file.

| Variable | Default | What it does |
|---|---|---|
| `MT_PORT` | `8080` | Host port the app is published on |
| `MT_DATA` | Docker volume `mediatracker-data` | Where `/data` lives. A volume name, or an absolute host path owned by uid 1000 |
| `TZ` | `UTC` | Time zone, used for backup file names |
| `MT_ADMIN_PASSWORD` | random, printed in the log | Password for the first admin. Only used when there are no users yet |
| `MT_ADMIN_USERNAME` | `admin` | Username for that first admin |
| `MT_BACKUP_KEEP` | `14` | Number of nightly backups to keep |
| `MT_TRASH_DAYS` | `30` | Days before items in the trash are deleted permanently |
| `MT_SESSION_DAYS` | `30` | How long a sign-in lasts |
| `MT_FORWARDED_ALLOW_IPS` | `*` | Which proxy IPs the app trusts for forwarded headers. Set it to your proxy's IP to be strict |
| `MT_TMDB_API_KEY`, `MT_DISCOGS_TOKEN`, `MT_UPCITEMDB_KEY` | none | Barcode lookup keys, if you'd rather set them here than in **Settings → Barcode lookup**. A key saved in the app takes priority |

The last five rows (from `MT_BACKUP_KEEP` down) aren't listed in the compose file. To use one, add it under `environment:` as `MT_BACKUP_KEEP: "${MT_BACKUP_KEEP:-14}"`.

## 5. Restore and roll back

**Restore a backup.** Stop the stack in Dockhand (or run `docker stop mediatracker`), then copy the backup over the live file. Running the copy as uid 1000 keeps the file's owner correct:

```bash
docker run --rm --user 1000 -v mediatracker_mediatracker-data:/data --entrypoint sh \
  ghcr.io/duffduff99/mediatracker:latest -c \
  'cp /data/backups/mediatracker-2026-11-05.db /data/mediatracker.db && rm -f /data/mediatracker.db-wal /data/mediatracker.db-shm'
```

Then start the stack again. If you use an `MT_DATA` folder, put that path in place of `mediatracker_mediatracker-data`. If you named the stack something other than `mediatracker`, run `docker volume ls` to find the volume name.

**Roll back to an older version of the app:** every image is also tagged `sha-<commit>` (see the repository's **Packages** page). Put that tag in the compose file instead of `latest`, then restore the backup taken before the update. Older versions don't know about newer database changes.

## 6. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Can't sign in: "Too many failed sign-ins" | 8 wrong passwords in 15 minutes locks that username and device for 15 minutes. Wait, or restart the container to clear it |
| Forgot the admin password | Another admin can reset it under **Settings → Users**. If you're the only admin, run: `docker exec -it mediatracker python -c "from app.db import connect; from app.security import hash_password; c=connect(__import__('pathlib').Path('/data/mediatracker.db')); c.execute(\"UPDATE users SET password_hash=? WHERE username='admin'\", (hash_password('a-new-password-here'),))"` |
| Scan button says the camera needs HTTPS | You opened the app over `http://` or by IP address. Use the HTTPS address from your reverse proxy |
| Camera permission denied | iPhone: Settings → Safari → Camera → Allow. Android: tap the lock icon in the address bar → Permissions → Camera |
| "Install app" isn't offered on Android | Usually means no HTTPS, or a certificate the phone doesn't trust |
| Barcode lookup says "couldn't connect" | The server can't reach that host. Check the firewall list in §2.6, then use **Settings → Barcode lookup → Try a barcode** |
| Barcode lookup says "limit reached" | The free UPCitemdb tier allows about 100 lookups a day; it resets the next day. Music lookups aren't affected |
| Barcode lookup says "key rejected" | Re-paste the key in **Settings → Barcode lookup** and press **Test** |
| Plex test says "couldn't reach Plex" | Check the address and port, and that the MediaTracker server can reach the Plex server. With Secure connections set to "Required", use the plex.direct address (§2.7) |
| Plex test says the token was refused | Get a fresh token (§2.7). Tokens change if you sign out of all devices in Plex |
| A TV season shows up twice (Movies and TV) | It was in Movies before the TV category existed. Merge the two titles, or select them in the grid and use **Change category…** |
| Phone can't reach it away from home | WireGuard isn't connected, or the tunnel doesn't route/resolve your internal hostname |
| Jira import fails with "413" or "too large" | Your reverse proxy's upload limit. See §2.3 |
| Container keeps restarting | Check the logs. The most common cause is an `MT_DATA` folder that uid 1000 can't write to. Fix with `sudo chown -R 1000:1000 /your/data/folder` |
| Dockhand can't find the compose file | Set the compose file path to `docker-compose.yml` (Dockhand defaults to `compose.yaml`) |
| Looks wrong after an update | Hard-refresh the browser (on a phone, close and reopen the app). The app caches its own files for speed |

## 7. If you ever want to make changes

See [DEVELOPMENT.md](DEVELOPMENT.md) for the code layout and how to run it locally. You don't need it for anything in this guide.
