# Role C: iOS app, live map, demo and submission (owner: fill in)

Paste this into your Claude session along with `PLAN.md` and `CLAUDE.md`.

**Your lane:** `ios/` (the Xcode project) and `convex/` (the Convex backend functions).

You build the only thing judges touch: a native iPhone app. After feature freeze (G4) you lead the video and the Devpost submission, with A and B supplying their sections.

## Stack
- **SwiftUI**, iOS 17+.
  - Photos: `PhotosPicker` plus the camera (`UIImagePickerController` wrapped for SwiftUI, or AVFoundation).
  - Location: `CoreLocation`. Map: **MapKit**.
- **Networking:** `URLSession`.
  - `POST /classify` sends multipart field `image` (a JPEG, long side ≤ 1280px). Resize with UIKit first; that also converts HEIC.
  - `POST /report` sends JSON.
  - Shapes: `contracts/*.schema.json`. Mirror them as `Codable` structs.
- **Live map backend:** Convex with the Swift client.
  - Package `https://github.com/convex/convex-swift`, product **`ConvexMobile`**.
  - `convex.subscribe(to:yielding:)` returns a Combine publisher that updates live.
  - Mutations are `async`.
  - Functions live in `convex/` (TypeScript): run `npx convex dev` with your own Convex login. The deployment URL goes in a gitignored config.
- **Don't wait for the API.** From minute one, bundle `contracts/examples/*.json` as a `MockAPI` that returns them. Switch to the real base URL (A's HTTPS tunnel) with one setting. **iOS App Transport Security needs HTTPS.** The cloudflared URL is HTTPS.
- **Running on a real iPhone:** Xcode + a free Apple ID (Personal Team) can install on your own device; trust the developer profile on the phone. TestFlight needs a paid account and review, so skip it. Also have the simulator flow working as a backup.

## Screens
1. **Capture:**
   - Camera / photo library.
   - GPS (manual address fallback).
   - Language picker. Default to the device language; offer at least English, Español, 中文, Filipino, Tiếng Việt, Русский.
2. **Result:**
   - Top category: display name, agency and confidence bar. The other two of the top 3 are tappable.
   - **If `abstain` is true:** "Not sure — here are my best guesses", and the user must pick one.
   - Then `/report`: a loading state, then Claude's title, description and next steps in the user's language, with an expandable English copy.
   - **If `emergency` is true:** a full-width "Call 911" banner with a `tel:911` link, and no filing flow.
   - Buttons: **Copy report**, **Open sf311.org** (`https://sf311.org`), and **Add to map**. We never auto-submit to the city.
3. **Live map (MapKit):**
   - Convex subscription to `reports:listRecent`, with pins colored by category, appearing live.
   - `reports:save` mutation stores the category, display name, agency, lat/lng, language, `title_en`, confidence and created time. **No photo.**
4. **About:** how it works, plus the results card. **Every number is loaded from `reports/*.json`** (bundled at G4), never typed by hand.

## Steps
- **C0 (by G0, 19:15):**
  - Xcode project in `ios/` (with a `.gitignore` for `xcuserdata/`, `DerivedData/`, `*.xcuserstate`), and a `convex/` init.
  - Confirm the **Anthropic "Claude for Public Benefit" prize rules** and the **Devpost video length limit** in Hive or Slack #ask-directors, and post both in team chat.
- **C1 (by G1, 20:00):** the capture screen plus `MockAPI` result screen on the simulator.
- **C2 (by G2, 23:00):** the real `/classify` and `/report` against A's tunnel, on a physical iPhone. Language picker. Abstain UX. Emergency banner.
- **C3 (by G3, 02:00):** Convex live map with save and subscribe, and the About screen.
- **Optional, if you have an iOS 26 iPhone:** run about 20 **val** photos through the official SF311 app's photo suggestion and record its pick → `reports/sf311_app_check.csv`. **Never press submit.** That's the only way we can say anything about SF311's accuracy.
- **C4 (G4, 05:00, feature freeze):**
  - Demo photos: take 10–20 photos of real street problems on your phone. **Never use test-set images. Never show encampment photos or identifiable people.**
  - Rehearse the 60 s live demo.
- **C5 (by G5, 07:00):**
  - Record the demo video (a screen recording plus voiceover). It must stand alone for sponsor judging.
  - Assemble Devpost: A writes "How we built it", B writes "Results / Challenges", and you write the rest.
  - Add at least 1 image (required), the GitHub link, and select the prizes from PLAN §8. **Only claim prizes we really use.**
- **Submit by 07:45.** All teammates are listed on Devpost. Screenshot the confirmation into team chat.

## Pitch (3 min + 2 min Q&A; you drive, A and B take the technical questions)
1. **(20 s) Problem:** dozens of 311 categories and agencies.
   - SF311's app already suggests a category from a photo, but **nobody publishes how accurate that is**, the app covers only 5 languages, and general-AI filers have been criticised by the city for getting reports wrong.
   - Read [docs/WHY.md](../WHY.md) §1 before writing a single pitch line. **Never claim we beat SF311's accuracy** unless we measured it.
2. **(60 s) Live demo on the iPhone:** photo → category + agency → report in Spanish → the pin appears on the map.
3. **(40 s) How:** 30k real SF 311 photos, three fine-tuned vision models, a leakage-proof split, calibrated "not sure", and Claude for language and a second opinion.
4. **(30 s) Results:** B's slide; every number has a JSON path.
5. **(30 s) Impact and next steps:**
   - a reproducible recipe any city with open 311 photo data can use to build **and audit** a photo categorizer
   - on-device inference

## Done means
- A fresh install on an iPhone completes photo → report → map pin in under 30 s against the real API. Attach a screen recording to your G3 PR.
- The video is uploaded and Devpost is submitted. Screenshot both confirmation pages into team chat.
