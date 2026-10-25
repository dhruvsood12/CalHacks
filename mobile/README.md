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

## Layout
- `src/app/`: one file per screen (Expo Router). `index.tsx` is Report, plus `map.tsx` and `about.tsx`. `_layout.tsx` holds the tabs.
- `src/components/`: shared, non-route components.
- Always add packages with `npx expo install <pkg>` so the versions match SDK 58.
