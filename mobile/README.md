# mobile/ (owner: C)

Expo (React Native) app for iOS and Android: Expo SDK 58, Expo Router, TypeScript. Live map data comes from Convex (functions in [`../convex/functions`](../convex/functions)).

## Run it
```bash
cd mobile
npm install
npx expo start
```
- **Phone:** install **Expo Go** (App Store / Play Store, a version that supports SDK 58) and scan the QR code. iPhone: scan with the Camera app. Android: scan from Expo Go.
- **Phone and laptop on different networks, or venue Wi-Fi blocks it:** `npx expo start --tunnel`.
- **iOS simulator:** press `i` in the Expo terminal.
- **Type-check:** `npm run typecheck`

- **Without the API:** leave `EXPO_PUBLIC_API_BASE_URL` unset and the app runs on `contracts/examples` (a "Mock data" badge shows). Set it in `mobile/.env` to A's tunnel URL to use the real `/classify`, `/context` and `/report`.

## Live map (Convex)
- **Local, no login (simulator only):** in `convex/`, run `CONVEX_AGENT_MODE=anonymous npx convex dev`, then put `EXPO_PUBLIC_CONVEX_URL=http://127.0.0.1:3210` in `mobile/.env` and restart Expo.
- **Cloud (needed for a real phone):** in `convex/`, run `npx convex login`, then `npx convex dev --configure new --dev-deployment cloud`, and put the printed `CONVEX_URL` in `mobile/.env` as `EXPO_PUBLIC_CONVEX_URL`.
- Without `EXPO_PUBLIC_CONVEX_URL` the app still works; Add to map is hidden and the Map tab says it isn't connected.
- `reports:clusters` groups same-category reports within 75 m; the pin shows the count, and the card shows the agency and why (usual agency for the category, model or resident pick, Claude agreement, location source).

## Location
- **Library photo:** uses the GPS stored in the photo (EXIF from the picker). On iOS this works with limited photo access, so the app never asks for photo-library permission.
- **Camera photo, or a photo with no GPS:** uses the phone's current location.
- **Location off, or wrong:** the resident types an address. It is geocoded and accepted only inside San Francisco; one that can't be placed is sent as text in the report note.
- The location line always says which of these it used ("from the photo", "your location", "address you entered").

## Tested on
- **iOS simulator (iPhone 17 Pro, iOS 26.3), Expo Go, against the mock API.** The demo runs on one iPhone.
- **Not tested:** Android, and the camera (the simulator has none). The Android EXIF path is written but has never run on a device.

## Layout
- `src/app/(tabs)/`: the tab screens. `index.tsx` is Report (capture), plus `map.tsx` and `about.tsx`.
- `src/app/result.tsx`: the result screen, pushed over the tabs.
- `src/api/`: contract types, the mock, and the HTTP client.
- `src/components/`: shared, non-route components.
- Always add packages with `npx expo install <pkg>` so the versions match SDK 58.
