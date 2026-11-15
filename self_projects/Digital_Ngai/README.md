# Digital Ngai

A voice-first personal life-logging Android app. The main interaction is:
press the mic, talk, and the app files what you said (a todo, or a journal
note) automatically. Location tracking and a Strava-style trail map run
continuously in the background. Everything is stored locally and exportable
as structured JSON so an AI assistant can actually understand your day
instead of guessing.

## Run it

Verified end-to-end on a Play Store-enabled Android emulator (`DigitalNgaiPlay`
AVD, API 34, arm64): build, install, background location auto-start,
map trail rendering (real OpenStreetMap tiles + polyline), todo/journal
add+delete, and screen-time permission grant flow all confirmed working with
simulated GPS and adb-driven usage stats. Voice recognition itself needs a
physical mic to test for real (see below).

**Emulator** (already set up on this machine):
```
export JAVA_HOME=/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
export ANDROID_HOME=/opt/homebrew/share/android-commandlinetools
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
emulator -avd DigitalNgaiPlay &
./gradlew installDebug
adb shell am start -n com.digitalngai.mirror/.MainActivity
```
The emulator has no real microphone input, so voice capture will time out
there — that's an emulator limitation, not an app bug. Real speech testing
needs a physical phone.

**Physical phone:**
1. Enable Developer Options + USB debugging, plug in via USB.
2. Same env vars as above, then `adb devices` to confirm it shows up, then
   `./gradlew installDebug`.
3. Grant location/mic/notification permissions when prompted — location
   tracking starts automatically the moment permission is granted, no toggle
   needed.
4. For screen time, go to Settings tab → "Open Settings to grant access" →
   enable Digital Ngai in the system's Usage Access list (Android requires
   this be granted manually; it's a sensitive permission with no popup).
5. **Battery:** Settings → Apps → Digital Ngai → Battery → set to
   "Unrestricted", or Android will eventually kill the background location
   service to save power.

## What's built (v0.3)

- **Voice capture (the main interaction)** — a mic button docked above the
  bottom nav on every tab. Tap, talk, release: Android's on-device speech
  recognizer transcribes it, and a keyword-based classifier
  (`ai/HeuristicClassifier`) auto-files it — "remind me to call mom" becomes
  a todo, everything else becomes a journal note. No typing required.
- **Location tracking — always on** — starts automatically the moment
  permission is granted (on app launch and on device boot), no manual
  switch. Runs as a continuous foreground service, like Strava.
- **Map tab** — your last 24h of location pings drawn as a trail line over
  real OpenStreetMap tiles (no API key needed, no Google/billing account).
- **Timeline** — merged feed of location pings, completed todos, and journal
  entries (including voice captures), newest first.
- **Todos / Journal manual forms** — kept as a deliberate fallback for quiet
  places, corrections, or editing. Journal entries (text and voice) can now
  be deleted from the list.
- **Screen time** — per-app foreground time via Android's UsageStatsManager.
  Requires a one-time manual grant in system Settings (the app deep-links
  you there); included in the AI export once granted.
- **Check-ins** — a WorkManager job posts a notification every 3 hours
  asking what you're doing; tapping it opens a quick-answer dialog.
- **Export for AI** — bundles the last N days of location, todos, journal
  entries, and screen time into one JSON file and opens the share sheet, so
  you can drop it into Claude (or any assistant) as real context about your
  life instead of vibes.

## Not built yet

- **Real LLM classification of voice transcripts.** The current
  `HeuristicClassifier` uses keyword matching ("remind me to...", "I need
  to..."), which is a stand-in for real understanding. Once you have an
  Anthropic API key from console.anthropic.com, tell me and I'll implement
  a `ClaudeApiClassifier` behind the same `EntryClassifier` interface — a
  drop-in swap, nothing else in the app changes.
- **Cloud sync.** Everything above is local-only (Room/SQLite on-device).
  Needs a Firebase project tied to *your* Google account, which I can't
  create for you:
  1. Go to https://console.firebase.google.com, create a project, add an
     Android app with package name `com.digitalngai.mirror`.
  2. Download `google-services.json`, drop it in `app/`.
  3. Tell me when it's there and I'll add the Firestore/Auth dependencies
     and sync layer.
- **Huawei Health integration.** Deferred at your request. Real sync needs
  Huawei's Health Kit SDK, which requires a Huawei Developer account
  (developer.huawei.com) and a registered Health Kit project — same
  category of external-account blocker as Firebase. When you're ready,
  either set that up (I'll wire in the SDK), or use Huawei Health's own
  manual export as a lighter-weight fallback with no account needed.
- **Automatic place naming** (reverse geocoding lat/lng into "Home",
  "Work", etc.) — currently the timeline and map show raw coordinates.
- **Pattern/automation analysis.** The export feature is step one toward
  "what can be automated in my life" — actually generating those insights
  is a follow-up once there's a few weeks of real data and real (not
  heuristic) classification is live.
- App icon is a placeholder vector, not custom art.

## Project layout

- `app/src/main/java/com/digitalngai/mirror/data/local/` — Room entities/DAOs
- `location/` — foreground service for background GPS logging, plus
  `LocationTrackingStarter` (auto-start on permission grant / boot)
- `work/` — WorkManager periodic check-in notifications
- `voice/` — `VoiceCaptureController` (on-device speech-to-text) and
  `VoiceRecorder` (raw audio memo capture, used by the Journal fallback)
- `ai/` — `EntryClassifier` seam: turns a transcript into a todo or journal
  note; `HeuristicClassifier` is the current keyword-based implementation,
  swap in an LLM-backed one later without touching callers
- `usage/` — `UsageStatsHelper`: screen time permission check, system
  Settings deep-link, and per-app usage query
- `export/` — AI-facing JSON exporter (location, todos, journal, screen time)
- `ui/` — Compose screens (Timeline, Map, Todos, Journal, Settings) + the
  single `AppViewModel`
