# Snap311 demo

- **Part 1:** the 3-minute video (storyboard, narration, shot list).
- **Part 2:** recording checklist.
- **Part 3:** physical-iPhone setup and test checklist.
- **Part 4:** live-demo runbook and fallbacks.

**What has been verified so far (Oct 24, iPhone 17 Pro simulator, Expo Go, cloud Convex):**
- **One uninterrupted run on the mock API,** screen-recorded: pick photo → "2001 Mission St · from the photo" → Español → Identify → "Not sure" → pick → Already reported? → Add mine as confirmation → Spanish report → Add to map → cluster badge **3 → 4** without a refresh → "why" card.
- **On A's API (stub classifier, run locally) with B's `/context`:** the right photo uploaded, `/classify` and `/context` answered with live DataSF data, and the app handled `/report` failing.
- **B ran a live Claude report** (`claude-opus-5-5`, 11.4 s, schema-valid) from a laptop (PR #40). It has not yet run through the app.

**Not yet verified:** the trained model behind the API, a real Claude report inside the app, and a physical iPhone. On-screen numbers in the mock (81%, "2 days ago, 38 m") change with the real API.

## Part 1: the 3-minute video
Demo-first: about 2:15 of app, 30 s of how it works and why it matters, 15 s for the problem. Narration is 356 words, about 2:30 at 140–150 words a minute, leaving about 30 s for taps and loading.

| Time | Shot (on screen) | Narration |
|---|---|---|
| 0:00–0:15 | Title card "Snap311", then the stat card: "44.4% of 28,431 new SF 311 reports (June 15–29, 2025) had a matching open report within 50 m", source `docs/evidence/city_context_stats.json` | "Reporting a pothole in San Francisco means finding the right category among dozens, dropping a pin, and guessing whether someone already reported it. In two weeks of the city's own data, 44% of new reports had a matching open report within 50 meters." |
| 0:15–0:40 | Phone screen recording. Report tab → **Choose photo** → the demo photo. Zoom on "<address> (±8 m) · from the photo". Tap **Español** | "Here's Snap311. I pick the photo I just took. The location fills itself in from the photo's own GPS, and the app says where it came from: the photo, my phone, or an address I typed. I'll ask for the report in Spanish." |
| 0:40–1:05 | **Identify the problem** → the top-3 cards with confidence and "usually handled by …". If the model abstains, show "Not sure" and tap the right card | "A vision model trained on about 30,000 of San Francisco's own 311 photos names the problem and the agency that usually handles it, with its confidence and two alternatives. When it isn't sure, it says so and lets me choose instead of guessing." |
| 1:05–1:25 | The **Already reported?** card (or the fix-time line) → **Add mine as confirmation** | "Before I file, it checks the city's open reports nearby and tells me how long this kind of problem usually takes to fix. If someone already reported it, I add mine as confirmation instead of a duplicate." |
| 1:25–1:55 | **Write my report** → the Spanish report → **Show the English copy for the city** → **Copy report** | "Then Claude looks at the photo and the model's guesses, confirms or corrects the category, and writes the report in my language, with an English copy for city staff. If it sees danger, like a downed wire, it tells me to call 911 instead. I paste the report into SF311 myself. Snap311 never files for anyone." |
| 1:55–2:20 | **Add to map** → **On the live map · See it** → the cluster badge ticks up by one → tap the pin → the "Why this agency" rows | "Every report lands on a live map, built on Convex live queries, so it appears for everyone without a refresh. Reports of the same kind within 75 meters group together. Tap one and you see exactly why it went to that agency: the city's usual agency for the category, whether the model or the resident chose it, whether Claude agreed, and where the location came from." |
| 2:20–2:45 | Architecture card: phone → FastAPI (`/classify`, `/context`, `/report`) → fine-tuned model · DataSF · Claude → Convex. Then one card: "Sealed, spatially separated test set · calibrated 'not sure'" | "Under the hood: three fine-tuned vision backbones, evaluated on a test set that is sealed and spatially separated from training, so the model is scored on blocks it has never seen. A calibrated threshold decides when to say 'not sure'. Live city data powers the duplicate check, and Claude powers language and a second opinion." |
| 2:45–3:00 | Closing card: "Snap311 · any resident, six languages, one photo" and the GitHub URL | "One photo, six languages, a ready-to-file report, and every decision visible. That's Snap311." |

**If B's final numbers are committed before recording,** replace the 2:20–2:45 card with the results slide, every number read from `reports/final_eval.json`. Don't say any accuracy number that isn't in that file.

**Cut list if over time:** drop Copy report (1:50) and the architecture card (keep only the narration). Never cut the map update.

**Which video to submit:**
- **Real backend:** record the storyboard above on the phone, and use that only if every check passes. `/health` shows a non-stub `model_version` and `report_ready: true`; then `/classify`, `/context`, a real Claude report, Add to map and a live map update all work on the phone.
- **Otherwise:** submit `mock-backup-labelled.mp4` (2:02). It is `mock-backup.mp4` with the idle first 13 s trimmed and **"MOCK DATA · no model or Claude calls"** burned into every frame. It also shows the "Mock data" badge, a report titled "Mock report: … no Claude call was made", and the map card's "Mock data: no Claude call was made". Narrate it as a mock-backend backup, and say the live map runs on Convex.
- `run1.mp4` is from an older build whose mock showed a canned Spanish report. Don't submit it.

## Part 2: recording checklist
- [ ] `curl -s https://<tunnel>/health` shows a real `model_version` (not `stub`) and `report_ready: true`. If not, record on mock and say so on screen.
- [ ] `cd convex && npm run seed -- '{"lat":..,"lng":..,"address":"..","category":"<label the model gives the demo photo>"}'`. The map shows 7 reports and a **3** badge, in the same category as the demo photo.
- [ ] Phone: Do Not Disturb on, brightness up, Location and Photos already granted to Expo Go.
- [ ] Demo photo taken today with Location on. No people, faces, plates or encampments. Not a dataset image.
- [ ] One full dry run, then re-seed so the badge starts at 3.
- [ ] Screen-record on the phone (Control Center → Screen Recording). Record narration separately and lay it over.
- [ ] Final video is 3:00 or less, uploaded to YouTube as public or unlisted, and the link is pasted into Devpost.

## Part 3: physical iPhone
**Setup (Mac):**
```bash
cd convex && npm run seed
```
```bash
cd mobile && npm install
```
Write `mobile/.env`:
```
EXPO_PUBLIC_CONVEX_URL=https://ideal-stork-400.convex.cloud
EXPO_PUBLIC_API_BASE_URL=https://<tunnel from Nirvaan>
```
Then start Expo over a tunnel, which works on venue Wi-Fi; accept if it offers to install `@expo/ngrok`:
```bash
cd mobile && npx expo start --tunnel --clear
```

**Phone:**
1. Install **Expo Go** from the App Store and check it supports SDK 58 (Expo Go → Settings shows the supported SDKs).
2. Scan the QR code with the Camera app. Expo Go opens Snap311.
3. Settings → Expo Go: Location **While Using**, Photos (selected or full access), Camera **On**.
4. Camera app → Settings → Location Services → Camera **While Using**, so new photos carry GPS.
5. The phone needs internet for Convex and the API. The tunnel means the phone and Mac don't need the same Wi-Fi.

**Checklist** (tick only what you saw on the phone):
| # | Check | Pass when |
|---|---|---|
| 1 | App launch | Report tab loads; Map tab shows "7 reports · 5 places" |
| 2 | Camera | **Take photo** opens the camera; the shot appears; the location line says "your location" |
| 3 | Library + EXIF | **Choose photo** → a photo taken with Location on; the location line says "<address> · from the photo" |
| 4 | Real classification | Result screen has **no** "Mock data" badge; `/health` showed a non-stub `model_version` |
| 5 | Real city context | "Already reported?" card or "No open reports of this kind nearby", plus a fix-time line |
| 6 | Real Claude report | Report text describes your photo in the chosen language, not "Mock report: … no Claude call was made" |
| 7 | Copy report | Paste into Notes: English title, description, category, agency, location |
| 8 | Add to map | Button changes to "On the live map · See it" |
| 9 | Live update | Map count goes up by one without pulling to refresh. Also try it with the simulator open on the Map tab; the pin should appear there too |
| 10 | Duplicate cluster | With the seed centred on your photo and the same category, the badge goes 3 → 4 |
| 11 | API failure | Turn on Airplane Mode before Identify: "didn't answer within 10 s" → turn it off → **Retry** succeeds |

## Part 4: live-demo runbook
### Setup (15 minutes before)
1. **Check the API:** `curl -s https://<tunnel>/health`. `model_version` must not be `stub` to claim the trained model, and `report_ready` must be `true` for Claude reports.
2. **Demo photo** with GPS (Part 3, step 4).
3. **Seed the map around that spot, in the photo's category** (check it once in the dry run): `cd convex && npm run seed -- '{"lat":..,"lng":..,"address":"..","category":"pavement_defect"}'`. Re-running also clears earlier mock, stub and rehearsal rows.
4. **App config and Expo** as in Part 3.
5. **Run the path once,** then re-seed.

### Exact taps
1. **Report** → **Choose photo** (tap once) → the demo photo (tap once).
   - Check: the preview is right, and the location line reads "<address> · from the photo".
2. **Español**.
3. **Identify the problem**.
   - It stays disabled, with a reason, until the location resolves.
4. If **"Not sure"**, tap the right category.
5. If **Already reported?** appears → **Add mine as confirmation**.
6. **Write my report** → **Show the English copy for the city**.
7. **Add to map** → **On the live map · See it** → the badge is one higher → tap it.

### What can fail, and the fallback
| # | Point | Symptom | Fallback |
|---|---|---|---|
| 1 | Expo on venue Wi-Fi | QR won't load, or a red bundling screen | `--tunnel`. Then the iOS simulator on the laptop. Then the recorded video |
| 2 | Photo picker | Wrong photo selected | A second tap on Choose photo while the picker opens can land on a grid cell; the app now ignores repeat taps. Check the preview before Identify |
| 3 | Photo has no GPS | "your location", or the address box appears | **Change** → type the address → Use this address. The line then says "address you entered" |
| 4 | Location permission | System prompt, or "Location is off" | Grant beforehand; on stage, type the address |
| 5 | `/classify` slow or down | "Couldn't identify this photo … didn't answer within 10 s" | **Retry**. If it stays down, restart Expo without `EXPO_PUBLIC_API_BASE_URL` (mock data, badge visible; about 30 s) |
| 6 | `/context` slow or down | "Couldn't check whether this was already reported" | **Retry**, or **Continue without the check**. The duplicate story is still on the map |
| 7 | `/report` (Claude) fails or is slow | "The report writer didn't answer" with the status; a real report can take about 10–20 s | **Try writing the report again**; photo, category and choices are kept. If it still fails, show the seeded cluster's why card |
| 8 | Different category from the model | New pin on its own (count 1) | Clusters merge only the same category. Re-seed with `"category"` set to what the model returned, or pick the matching card |
| 9 | Photo far from the seed | New pin isn't grouped | Re-seed with the photo's coordinates |
| 10 | Convex unreachable | Map says "Connecting to the live map…" | Needs internet; fall back to the video |
| 11 | Reverse geocoding slow | Coordinates instead of an address | Fine; the source label is still shown |
| 12 | Leftover test pins | More pins than expected | `npm run seed` again |
