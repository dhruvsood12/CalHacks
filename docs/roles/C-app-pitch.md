# Role C: Product, demo and pitch (owner: fill in)

Paste this into your Claude session along with `PLAN.md` and `CLAUDE.md`. You own `app/`, the demo, the Devpost page and the video. The judges experience the project through your work.

**Your deliverables:**
1. a phone web app that runs the full flow
2. a live map on Convex
3. a 3-minute pitch
4. a demo video
5. the Devpost submission by **07:45**

## Stack (default; change it only before G1, in a `shared` PR)
- **App:** React + Vite + TypeScript, mobile-first, deployed to Vercel (or a `cloudflared` tunnel from a laptop).
- **Backend for reports and the map:** Convex.
  - a `reports` table: category, display name, agency, lat/lng, language, title, description_en, created time, confidence. **No image.**
  - a `saveReport` mutation
  - a `listRecentReports` query, used live by the map
- **Map:** Leaflet + OpenStreetMap tiles.

## Screens
1. **Capture:**
   - `<input type="file" accept="image/*" capture="environment">` plus "upload from gallery"
   - Resize on the client to a JPEG with long side ≤ 1280px (canvas). This also converts iPhone HEIC.
   - Ask for GPS permission; a manual address field is the fallback.
   - Language picker. Default to the browser language; offer at least English, Español, 中文, Filipino, Tiếng Việt, Русский.
2. **Result:**
   - the top category (display name, agency, confidence bar) and the other two of the top 3 as tappable alternatives
   - **If `abstain` is true:** "Not sure — here are my best guesses", and the user must pick one.
   - Then call `/report`. Show the streaming state, then Claude's title and description in the user's language, an English copy, and "what happens next".
   - **If `emergency` is true:** a full-width "Call 911" banner, and no filing flow.
   - Buttons: **Copy report** and **Open sf311.org**. We never auto-submit to the city.
   - On confirm: `saveReport` to Convex.
3. **Live map:** markers by category color, newest first. A side list. Updates live (a Convex query, no refresh).
4. **About / How it works:** the one-slide architecture and the metrics from `reports/*.json`, generated from the JSON, never typed by hand.

Build against B's **stub URL from G1**. API shapes are in `contracts/`, and example responses are in `contracts/examples/`.

## Steps
- **C0 (by G0, 18:45):** scaffold `app/` (Vite React TS) and `npx convex dev` (each person uses their own Convex login; put the deployment URL in `.env.local`, which is gitignored). **Confirm the Anthropic "Claude for Public Benefit" rules** in Hive or Slack #ask-directors, write them into PLAN §8 in a PR, and confirm the Devpost video length limit.
- **C1 (by G1, 19:30):** the capture screen posts to the stub `/classify` from a real phone.
- **C2 (by G2, 22:30):** the result screen, the `/report` flow and language selection work end to end against B's API.
- **C3 (by G3, 01:30):** the Convex live map, the emergency banner, abstain UX, deployed URL.
- **C4 (by G4, 04:30):**
  - Pitch deck (5–6 slides): problem, demo, how it works, results, impact, ask.
  - **Every statistic either links a source or comes from `reports/*.json`.**
  - Demo photos: take 10–20 of your own photos of real street problems on the way in, or use **val** images. **Never use test images in the demo. Never show encampment photos or identifiable people.**
- **C5 (by G5, 06:30):**
  - Record the demo video (sponsors judge without us, so this must stand alone).
  - Write Devpost: what it does, how we built it, the challenges (label noise, leakage), accomplishments with real numbers, what's next.
  - Add the GitHub link, at least one image (required), and select the prize categories from PLAN §8. **Only claim prizes we really use.**
- **Submit by 07:45.** Every teammate is listed on Devpost.

## Pitch outline (3 min + 2 min Q&A)
1. **(20 s) Problem:** reporting street problems is confusing (dozens of categories and agencies) and English-first.
2. **(60 s) Live demo:** photo → category + agency → report in Spanish → it appears on the map.
3. **(40 s) How:**
   - 30k real SF 311 photos
   - a fine-tuned vision model with a leakage-proof spatial split
   - calibrated, so it says "not sure" instead of guessing
   - Claude for language and a second opinion
4. **(30 s) Results:**
   - top-1 and top-3 with confidence intervals
   - vs Claude zero-shot and vs the frozen baseline
   - accuracy when the model is confident
5. **(30 s) Impact and next steps:** any city running 311 (the same schema is used by many cities via Open311), language access, and routing that cuts misfiled reports.

**Q&A prep (likely questions):**
- Why not just use Claude?
- How do you know it's not overfit?
- What about privacy and encampments?
- What happens with a non-street photo?

## Done means
- A phone that has never seen the app opens the deployed URL and completes photo → report → map in under 30 s.
- The video is uploaded and Devpost is submitted. Screenshot both confirmation pages into the team chat.
