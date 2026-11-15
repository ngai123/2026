# Running the arena 24/7 (macOS launchd)

The backend is what must stay alive — it runs the trading loop and the
mark-to-market job. The browser tab and `npm run dev` are just viewers.

`com.aitradingarena.backend.plist` runs the backend under **launchd** so it:
- starts automatically at login (`RunAtLoad`)
- restarts itself if it crashes (`KeepAlive`)
- keeps the Mac awake while running (`caffeinate -dimsu`)

## Install

```bash
cp deploy/com.aitradingarena.backend.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.aitradingarena.backend.plist
```

It's now running on http://localhost:8000 and will survive reboots.

## Manage

```bash
launchctl list | grep aitradingarena            # is it running?
tail -f deploy/backend.err.log                  # logs
launchctl unload -w ~/Library/LaunchAgents/com.aitradingarena.backend.plist  # stop
```

After editing the plist, `unload` then `load` again.

## Notes
- Keep the laptop **plugged in and the lid open** — `caffeinate` blocks idle
  sleep, but closing the lid still sleeps most Macs.
- The frontend (dashboard viewer) isn't covered here; run `npm run dev` in
  `frontend/` when you want to look, or deploy it separately. Trading continues
  with or without it.
- Paths in the plist are absolute — if you move the project, update them.
