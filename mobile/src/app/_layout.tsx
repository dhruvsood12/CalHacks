import { ConvexProvider } from 'convex/react';
import { Stack } from 'expo-router';
import { convex } from '../live';

function Screens() {
  return (
    <Stack>
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="result" options={{ title: 'Result', headerBackTitle: 'Back' }} />
    </Stack>
  );
}

export default function RootLayout() {
  return convex ? (
    <ConvexProvider client={convex}>
      <Screens />
    </ConvexProvider>
  ) : (
    <Screens />
  );
}
