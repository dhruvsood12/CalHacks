# Role C: Mobile app (iOS + Android), live map, demo and submission (owner: Dhruv, @dhruvsood12)

Paste this into your Claude session along with `PLAN.md` and `CLAUDE.md`.

**Your lane:** `mobile/` (the Expo / React Native app) and `convex/` (the Convex backend functions).

You build the only thing judges touch: a phone app that runs on **iOS and Android** from one codebase. (Expo was chosen over SwiftUI so it also works on Android.) After feature freeze (G4) you lead the video and the Devpost submission, with A and B supplying their sections.

## Stack
- **Expo (React Native) + TypeScript.**
  - Photos: `expo-image-picker` for camera + library. Request `exif: true`, so library photos keep their GPS.
  - Location: `expo-location`.
  - Resize to JPEG with long side ≤ 1280px using `expo-image-manipulator`. That also converts HEIC.
- **Networking:** `fetch`.
  - `POST /classify` sends multipart field `image` + optional `lat`/`lng`.
  - `GET /context?label=&lat=&lng=`
  - `POST /report` sends JSON.
  - Shapes: `contracts/*.schema.json`. Mirror them as TypeScript types.
- **Live map backend:** Convex.
  - Functions in `convex/`.
  - The app uses the Convex React client (`useQuery` updates live, `useMutation` saves).
  - The deployment URL goes in config, not hard-coded.
- **Don't wait for the API.** Bundle `contracts/examples/*.json` as a mock that returns them, and switch to A's HTTPS tunnel URL with one setting.
- **Running on phones:** Expo Go or a development build on a real iPhone and a real Android phone, with a simulator/emulator as backup.

## Screens
1. **Capture, with automatic geotagging:**
   - Camera / photo library.
   - **Location with zero taps:**
     - Camera photos use `expo-location`, requested once at capture, with accuracy shown.
     - **Library photos use the photo's own EXIF GPS** (`exif: true` in `expo-image-picker`).
   - Reverse-geocode (`expo-location` `reverseGeocodeAsync`): "📍 3601 Lyon St (±8 m)". Tap to adjust on a map.
   - **Manual pin only as a fallback.** That's a direct contrast with SF311, which makes the resident place a pin.
   - Language picker. Default to the device language; offer at least English, Español, 中文, Filipino, Tiếng Việt, Русский.
2. **Result:**
   - Send `lat`/`lng` with `/classify` (it uses them as a second signal).
   - Top category: display name, "usually handled by" agency, and confidence bar. The other two of the top 3 are tappable.
   - **Already reported? card** (from `GET /context`): "Someone reported this 2 days ago, 38 m away — still open." Two buttons:
     - **Add mine as confirmation:** copies the case number + "also seen on <date>" into the report.
     - **File anyway**
   - **Fix-time line:** "Similar issues are typically fixed in about 6 days" (median; p75 as "most within 14 days").
   - **If `abstain` is true:** "Not sure — here are my best guesses", and the user must pick one.
   - Then `/report`: a loading state, then Claude's title, description and next steps in the user's language, with an expandable English copy.
   - **If `emergency` is true:** a full-width "Call 911" banner with a `tel:911` link, and no filing flow.
   - Buttons: **Copy report**, **Open sf311.org** (`https://sf311.org`), and **Add to map**. We never auto-submit to the city.
3. **Live map:**
   - Convex subscription to `reports:listRecent`, with pins colored by category, appearing live.
   - `reports:save` mutation stores the category, display name, agency, lat/lng, language, `title_en`, confidence and created time. **No photo.**
4. **About:** how it works, plus the results card. **Every number is loaded from `reports/*.json`** (bundled at G4), never typed by hand.

## Steps
- **C0 (by G0, 19:15):**
  - Expo project in `mobile/` and a `convex/` init.
  - Confirm the **Anthropic "Claude for Public Benefit" prize rules** and the **Devpost video length limit** in Hive or Slack #ask-directors, and post both in team chat.
- **C1 (by G1, 20:00):** the capture screen plus `MockAPI` result screen on the simulator.
- **C2 (by G2, 23:00):** the real `/classify`, `/context` and `/report` against A's tunnel, on a physical iPhone. **Automatic geotagging** (GPS + photo EXIF + address). Already-reported card. Fix-time line. Language picker. Abstain UX. Emergency banner.
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
   - SF311's app already suggests a category from a photo, but **nobody publishes how accurate that is**.
   - It makes you place a pin.
   - It doesn't warn you that **44% of new reports duplicate an open one nearby** (`docs/evidence/city_context_stats.json`).
   - It doesn't tell you how long a fix takes.
   - It covers 5 languages.
   - Read [docs/WHY.md](../WHY.md) §1 before writing a single pitch line. **Never claim we beat SF311's accuracy** unless we measured it.
2. **(60 s) Live demo on the iPhone:** photo → location pins itself → category + agency → **"already reported 2 days ago, 38 m away"** → fix time → report in Spanish → the pin appears on the map.
3. **(40 s) How:** 30k real SF 311 photos, three fine-tuned vision models, a leakage-proof split, calibrated "not sure", and Claude for language and a second opinion.
4. **(30 s) Results:** B's slide; every number has a JSON path.
5. **(30 s) Impact and next steps:**
   - a reproducible recipe any city with open 311 photo data can use to build **and audit** a photo categorizer
   - on-device inference

## Done means
- A fresh install on an iPhone completes photo → report → map pin in under 30 s against the real API. Attach a screen recording to your G3 PR.
- The video is uploaded and Devpost is submitted. Screenshot both confirmation pages into team chat.
