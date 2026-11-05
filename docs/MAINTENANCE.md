# Running and maintaining MediaTracker

This guide assumes you never change the app's features. It covers what you do need to do: install it once, keep it updated, and make sure the data is safe.

**Short version:** once a month, pull the new image and restart the container (2 minutes). Every few months, check that backups are being written and copied off the server. That's it.

---

## 1. What's running

| Piece | Where |
|---|---|
| The app | One container, `ghcr.io/duffduff99/mediatracker`, listening on port **8080** |
| Your data | One file, `data/mediatracker.db`, in the folder mounted at `/data` |
| Nightly backups | `data/backups/mediatracker-YYYY-MM-DD.db` (the last 14 are kept) |

There is no separate database server, cache or queue. If the container and the `data` folder are fine, the app is fine.

## 2. First install

### 2.1 Start the container

In Dockhand (or any Docker host), create a stack from [`docker-compose.yml`](../docker-compose.yml). Adjust these lines if needed:

- `ports`: change the left-hand `8080` if that port is taken on the host.
- `volumes`: `./data:/data` keeps the data next to the compose file. Use an absolute path (for example `/srv/mediatracker/data:/data`) if you prefer. **This folder is what you back up.**
- `TZ`: your time zone, so backup file names use your local date.

Then deploy it, or run `docker compose up -d`.

**If the GitHub repository is private**, the image in GitHub's registry is private too, so the server needs permission to pull it. Either:
- make the package public (it contains only the app, never your data): on GitHub, go to your profile → **Packages** → `mediatracker` → **Package settings** → **Change visibility**; or
- give Dockhand/Docker a registry login for `ghcr.io`, with your GitHub username and a [personal access token](https://github.com/settings/tokens) that has only the `read:packages` scope.

Alternatively, build the image on the server from a git checkout: in the compose file, replace `image:` with `build: .`.

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

## 3. Routine maintenance

### Monthly: update (≈ 2 minutes)

Updates contain security fixes for Python, the base image and the libraries the app uses, even when nothing visible changes.

1. In Dockhand, open the MediaTracker stack and **pull** the latest image, then **redeploy/recreate** the container. From a shell:
   ```bash
   docker compose pull
   docker compose up -d
   ```
2. Open the app and check that it loads and search works.

Database changes are applied automatically when the new version starts, and a backup from that night already exists. To go back to a previous version, see §5.

New images appear when code is merged to `main` on GitHub. Dependabot opens monthly pull requests with library updates. The **Test and build image** check runs the automated tests on each one; if it's green, merging it publishes a new image.

### Every few months: check backups

1. Look in `data/backups/`. You should see one file per night, up to 14.
2. Make sure your existing Docker-volume backup includes the `data` folder, and that copies leave the server (to a NAS or offsite).
3. Once in a while, do a test restore (§5) into a scratch container. A backup you've never restored is a guess.

**Why the nightly copies matter:** copying `mediatracker.db` while the app is writing can produce a damaged copy. The files in `data/backups/` are made with SQLite's own backup function, so they are always consistent. Your volume backup will pick them up.

You can also download a backup at any time: **Settings → Import & export → Download backup**.

### Yearly: tidy up

- In **Settings → Users**, remove anyone who no longer needs access.
- Look through the **Trash**. Items are deleted permanently after 30 days anyway.

## 4. Settings you can change (environment variables)

| Variable | Default | What it does |
|---|---|---|
| `TZ` | UTC | Time zone, used for backup file names |
| `MT_ADMIN_PASSWORD` | random, printed in the log | Password for the first admin. Only used when there are no users yet |
| `MT_ADMIN_USERNAME` | `admin` | Username for that first admin |
| `MT_BACKUP_KEEP` | `14` | Number of nightly backups to keep |
| `MT_TRASH_DAYS` | `30` | Days before items in the trash are deleted permanently |
| `MT_SESSION_DAYS` | `30` | How long a sign-in lasts |
| `MT_FORWARDED_ALLOW_IPS` | `*` | Which proxy IPs the app trusts for forwarded headers. Set it to your proxy's IP to be strict |

## 5. Restore and roll back

**Restore a backup:**

```bash
docker compose stop
cp data/backups/mediatracker-2026-11-05.db data/mediatracker.db
rm -f data/mediatracker.db-wal data/mediatracker.db-shm
docker compose start
```

**Roll back to an older version of the app:** every image is also tagged `sha-<commit>` (see the repository's **Packages** page). Put that tag in the compose file instead of `latest`, then restore the backup taken before the update. Older versions don't know about newer database changes.

## 6. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Can't sign in: "Too many failed sign-ins" | 8 wrong passwords in 15 minutes locks that username and device for 15 minutes. Wait, or restart the container to clear it |
| Forgot the admin password | Another admin can reset it under **Settings → Users**. If you're the only admin, run: `docker exec -it mediatracker python -c "from app.db import connect; from app.security import hash_password; c=connect(__import__('pathlib').Path('/data/mediatracker.db')); c.execute(\"UPDATE users SET password_hash=? WHERE username='admin'\", (hash_password('a-new-password-here'),))"` |
| Scan button says the camera needs HTTPS | You opened the app over `http://` or by IP address. Use the HTTPS address from your reverse proxy |
| Camera permission denied | iPhone: Settings → Safari → Camera → Allow. Android: tap the lock icon in the address bar → Permissions → Camera |
| "Install app" isn't offered on Android | Usually means no HTTPS, or a certificate the phone doesn't trust |
| Phone can't reach it away from home | WireGuard isn't connected, or the tunnel doesn't route/resolve your internal hostname |
| Jira import fails with "413" or "too large" | Your reverse proxy's upload limit. See §2.3 |
| Container keeps restarting | Check the logs. The most common cause is a `data` folder that the container user (uid 1000) can't write to. Fix with `sudo chown -R 1000:1000 data` |
| Looks wrong after an update | Hard-refresh the browser (on a phone, close and reopen the app). The app caches its own files for speed |

## 7. If you ever want to make changes

See [DEVELOPMENT.md](DEVELOPMENT.md) for the code layout and how to run it locally. You don't need it for anything in this guide.
