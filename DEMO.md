# Snap311 demo

Part 1 is the 3-minute video script. Part 2 is the live-demo runbook: setup, exact taps, and what to do when something fails.

## Part 1: video script (about 3:00)

**0:00–0:15 · The problem**
> In San Francisco, reporting a pothole means picking from dozens of categories, dropping a pin, and guessing whether someone already reported it. Almost half the time, someone has.

On screen: SF311's category menu, then the line "44.4% of new reports had an open one of the same type within 50 m" with its source, `docs/evidence/city_context_stats.json`.

**0:15–1:00 · Capture**
> Here's Snap311. I pick the photo I just took. Notice the location: it filled itself in from the photo's own GPS, and it says so. If the photo has no location, it uses my phone's. If that's off, I type an address.

On screen:
- Choose photo.
- Zoom on the location line, "2001 Mission St · from the photo".
- Tap Español.
- Tap Identify the problem.

**1:00–1:45 · The routing decision**
> In a second: pothole, 81%, usually handled by Public Works Street and Sewer Repair, with two alternatives. If the model isn't sure, it says so and I choose. It never guesses confidently. Then Claude writes the report in Spanish, with an English copy for the city. I copy it into SF311 myself. We never file for anyone.

On screen:
- The top-3 cards.
- A cut to the "Not sure" screen from a second photo.
- Write my report, the Spanish report, then Show the English copy.

**1:45–2:30 · The duplicate catch**
> Before I file, it checks the city's live data: someone reported this two days ago, 38 meters away, still open. I add mine as confirmation instead of a duplicate. It even tells me similar problems usually get fixed in about six days. And on the live map, this block now has four reports of the same pothole.

On screen:
- The "Already reported?" card, then Add mine as confirmation.
- Add to map, then the map with the pin badge going from 3 to 4.

**2:30–3:00 · The close**
> Tap the pin and you see exactly why it went to that agency: the usual agency for this category in the city's own history, whether the model or the resident chose it, whether Claude agreed, and where the location came from. Every input is visible. Any resident, any language, one photo, and the report is ready to file.

On screen:
- The pin card with the "Why this agency" rows.
- End on the map with the legend.

Recording notes:
- Record on the iPhone with screen recording and add the voiceover afterwards.
- Never show encampment photos or identifiable people.
- If the app is on mock data, the **Mock data** badge is visible. Say so, or record against the real API.

## Part 2: live-demo runbook

### Setup (10 minutes before)
1. **Demo photo.** Take a photo of a real pothole with Location on in the camera, so the photo carries GPS. Note roughly where it was taken.
2. **Seed the map around that spot.** The new report then joins a cluster of 3:
   ```bash
   cd convex && npm run seed -- '{"lat":37.76512,"lng":-122.41948,"address":"2001 Mission St"}'
   ```
   - Use the photo's own coordinates. With no arguments the cluster stays at 2001 Mission St.
   - It must be inside San Francisco, because the map opens on SF.
   - Expected result: the map shows **7 reports · 5 places** and a **3** badge.
3. **App config.** `mobile/.env` has `EXPO_PUBLIC_CONVEX_URL=https://ideal-stork-400.convex.cloud`, plus `EXPO_PUBLIC_API_BASE_URL=<A's tunnel>` if the real API is up. Then:
   ```bash
   cd mobile && npx expo start --tunnel --clear
   ```
   Open the project in Expo Go on the demo iPhone.
4. **Grant permissions once,** so no system prompt appears on stage: Location (While Using) and Photos.
5. **Run the path below once end to end.** Then re-run step 2 so the count starts at 3 again.

### Exact taps
1. **Report** tab → **Choose photo** → the demo photo.
   - Check: the location line reads "<address> · from the photo".
2. Tap **Español**.
3. Tap **Identify the problem**.
   - Check: the top card is *Pothole or street pavement damage* with "Usually handled by PW - Street and Sewer Repair".
   - If it shows "Not sure", tap the pothole card.
4. **Already reported?** card → **Add mine as confirmation**.
5. **Write my report** → the Spanish report appears.
   - Tap **Show the English copy for the city**.
6. **Add to map** → **On the live map · See it**.
7. On the **Map**, the badge on the cluster now reads **4**.
   - Tap it to show the agency and the four "Why this agency" rows.

### What can fail, and the fallback
| # | Point | Symptom | Fallback |
|---|---|---|---|
| 1 | Expo on venue Wi-Fi | QR won't load, or a red bundling screen | `--tunnel`. Then the iOS simulator on the laptop. Then the recorded video |
| 2 | Photo picker | It returns a different photo than the one tapped (seen in the simulator) | Check the image and location line before Identify; pick again |
| 3 | Photo has no GPS | Location reads "your location" or asks for an address | Tap **Change**, type the seeded address, Use this address. The line then says "address you entered", which is still provenance |
| 4 | Location permission | System prompt or "Location is off" | Grant it beforehand (setup step 4). On stage, type the address |
| 5 | `/classify` slow or down | "Couldn't identify this photo … didn't answer within 8 s" | **Retry**. If still down, restart Expo with `EXPO_PUBLIC_API_BASE_URL` removed (mock data, badge visible; about 30 s) |
| 6 | `/context` slow or down | "Couldn't check whether this was already reported" | **Continue without the check**. The duplicate story is still told on the map (the cluster badge) |
| 7 | `/report` (Claude) fails | "The report writer is unavailable" | **Add to map only exists after a report.** Go to the Map tab and tap the seeded cluster (count 3) to show the why card. Or switch to mock data as in row 5 |
| 8 | Different category from the model | New report lands as its own pin (count 1), not in the cluster | Clusters only merge the same category. Tap the pothole card on the result screen before writing the report, or show the seeded cluster |
| 9 | Photo far from the seed | New pin is not grouped with the cluster | Re-seed with the photo's coordinates (setup step 2) |
| 10 | Convex unreachable | Map says "Connecting to the live map…" | Needs internet. Check the laptop or phone network; fall back to the video |
| 11 | Reverse geocoding slow | Location shows coordinates instead of an address | Fine to continue. The provenance label is still shown |
| 12 | Leftover test pins | More pins than expected | `npm run seed` again; it clears seed and rehearsal rows |
