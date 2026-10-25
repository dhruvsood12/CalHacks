# Snap311 demo

Part 1 is the 3-minute video script. Part 2 is the live-demo runbook: setup, exact taps, and what to do when something fails.

**What was verified (Oct 24, iPhone 17 Pro simulator, Expo Go, cloud Convex):**
- **One uninterrupted run on the mock API:** pick photo → "2001 Mission St · from the photo" → Español → Identify → "Not sure" → pick → Already reported? → Add mine as confirmation → Spanish report → Add to map. The cluster badge went **3 → 4** without a refresh, and the pin card showed the four "why" rows.
- **On A's API (stub classifier, run locally) with B's `/context`:** the right photo uploaded, `/classify` and `/context` answered, and the app handled `/report` failing.

**Not yet verified:** a real Claude report, the trained model, and a physical iPhone. Numbers on screen (81%, "2 days ago, 38 m") come from the mock and change with the real API.

## Part 1: video script (about 3:00)

**0:00–0:15 · The problem**
> In San Francisco, reporting a pothole means picking from dozens of categories, dropping a pin, and guessing whether someone already reported it. In two weeks of the city's own data, 44% of new reports had a matching open report within 50 meters.

On screen: the line "44.4% of 28,431 new reports, June 15–29 2025, had an earlier same-type report still open within 50 m" with its source, `docs/evidence/city_context_stats.json`.

**0:15–1:00 · Capture**
> Here's Snap311. I pick the photo I just took. The location filled itself in from the photo's own GPS, and it says so. If the photo has no location, it uses my phone's. If that's off, I type an address.

On screen:
- Choose photo.
- Zoom on the location line, "<address> · from the photo".
- Tap Español.
- Tap Identify the problem.

**1:00–1:45 · The routing decision**
> The model names the problem and the agency that usually handles it, with two alternatives and its confidence. When it isn't sure, it says so and I choose instead of it guessing. Then Claude looks at the photo and the guesses, confirms the category, and writes the report in Spanish with an English copy for the city. I copy it into SF311 myself. We never file for anyone.

On screen:
- The top-3 cards.
- A cut to the "Not sure" screen if the model abstains.
- Write my report, the Spanish report, then Show the English copy.

**1:45–2:30 · The duplicate catch**
> Before I file, it checks the city's open reports nearby and the typical fix time. If someone already reported it, I can add mine as confirmation instead of a duplicate. And on the live map, this block now has one more report of the same pothole.

On screen:
- The "Already reported?" card, if the city data has a nearby open report. If not, skip straight to the map.
- Add to map, then the map with the cluster badge going up by one.

**2:30–3:00 · The close**
> Tap the pin and you see exactly why it went to that agency: the usual agency for this category in the city's own history, whether the model or the resident chose it, whether Claude agreed, and where the location came from. Every input is visible. One photo, six languages, and the report is ready to file.

On screen:
- The pin card with the "Why this agency" rows.
- End on the map with the legend.

Recording notes:
- Record on the device with screen recording and add the voiceover afterwards.
- Never show encampment photos, identifiable people or test-set photos.
- If the app is on mock data, the **Mock data** badge is visible and the pin card says "Mock data: no model or Claude call was made". Say so, or record against the real API.

## Part 2: live-demo runbook

### Setup (15 minutes before)
1. **Check the API** (A's HTTPS tunnel):
   ```bash
   curl -s https://<tunnel>/health
   ```
   - `model_version` must not be `stub` to claim the trained model.
   - `report_ready` must be `true` for Claude reports.
2. **Demo photo.** Take a photo of a real street problem with Location on in the Camera app, so the photo carries GPS. Note roughly where it was taken.
3. **Seed the map around that spot,** so the new report joins a cluster of 3:
   ```bash
   cd convex && npm run seed -- '{"lat":37.76512,"lng":-122.41948,"address":"2001 Mission St"}'
   ```
   - Use the photo's own coordinates; with no arguments the cluster stays at 2001 Mission St.
   - It must be inside San Francisco.
   - Expected result: the map shows **7 reports · 5 places** and a **3** badge.
   - Re-running also clears earlier mock, stub and rehearsal rows.
4. **App config.** `mobile/.env`:
   ```
   EXPO_PUBLIC_CONVEX_URL=https://ideal-stork-400.convex.cloud
   EXPO_PUBLIC_API_BASE_URL=https://<tunnel>
   ```
   Then start Expo and open the project in Expo Go on the demo phone:
   ```bash
   cd mobile && npx expo start --tunnel --clear
   ```
5. **Grant permissions once,** so no system prompt appears on stage: Location (While Using) and Photos.
6. **Run the path below once end to end.** Then re-run step 3 so the count starts at 3 again.

### Exact taps
1. **Report** tab → **Choose photo**, tapped once → tap the demo photo once.
   - Check: the photo preview is the right one and the location line reads "<address> · from the photo".
2. Tap **Español**.
3. Tap **Identify the problem**.
   - It stays disabled, with a reason, until the location resolves.
4. If **"Not sure"**, tap the right category card. Otherwise the model's top pick is already selected.
5. If **Already reported?** appears, tap **Add mine as confirmation**.
6. **Write my report** → the Spanish report appears → **Show the English copy for the city**.
7. **Add to map** → **On the live map · See it**.
8. On the **Map**, the cluster badge is one higher. Tap it to show the agency and the "Why this agency" rows.

### What can fail, and the fallback
| # | Point | Symptom | Fallback |
|---|---|---|---|
| 1 | Expo on venue Wi-Fi | QR won't load, or a red bundling screen | `--tunnel`. Then the iOS simulator on the laptop. Then the recorded video |
| 2 | Photo picker | Wrong photo selected | Cause found in simulator testing: a second tap on Choose photo landed on a grid cell while the picker opened. The app now ignores repeat taps while the picker is open. Check the preview before Identify; pick again if wrong |
| 3 | Photo has no GPS | Location reads "your location", or the address box appears | Tap **Change**, type the address, then Use this address. The line then says "address you entered" |
| 4 | Location permission | System prompt, or "Location is off" | Grant it in setup step 5. On stage, type the address |
| 5 | `/classify` slow or down | "Couldn't identify this photo … didn't answer within 8 s" | **Retry**. If it stays down, restart Expo without `EXPO_PUBLIC_API_BASE_URL` (mock data, badge visible; about 30 s) |
| 6 | `/context` slow or down | "Couldn't check whether this was already reported" | **Retry**, or **Continue without the check**. The duplicate story is still on the map |
| 7 | `/report` (Claude) fails | "The report writer didn't answer", with the server status | **Try writing the report again**; photo, category and choices are kept. If it still fails, show the seeded cluster's why card on the Map tab |
| 8 | Model picks a different category | New pin lands on its own (count 1), not in the cluster | Clusters merge only the same category. Pick the matching card before writing the report, or show the seeded cluster |
| 9 | Photo far from the seed | New pin isn't grouped | Re-seed with the photo's coordinates (setup step 3) |
| 10 | Convex unreachable | Map says "Connecting to the live map…" | Needs internet. Check the network; fall back to the video |
| 11 | Reverse geocoding slow | Location shows coordinates, not an address | Fine to continue; the source label is still shown |
| 12 | Leftover test pins | More pins than expected | `npm run seed` again |
