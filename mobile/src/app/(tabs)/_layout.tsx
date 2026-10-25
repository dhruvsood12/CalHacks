import Ionicons from '@expo/vector-icons/Ionicons';
import { Tabs } from 'expo-router';
import { ComponentProps } from 'react';

type IconName = ComponentProps<typeof Ionicons>['name'];

const ACTIVE = '#0a66c2';
const INACTIVE = '#8e8e93';

function tabIcon(name: IconName) {
  return ({ focused, size }: { focused: boolean; size: number }) => (
    <Ionicons name={name} color={focused ? ACTIVE : INACTIVE} size={size} />
  );
}

export default function TabsLayout() {
  return (
    <Tabs screenOptions={{ tabBarActiveTintColor: ACTIVE, tabBarInactiveTintColor: INACTIVE }}>
      <Tabs.Screen name="index" options={{ title: 'Report', tabBarIcon: tabIcon('camera') }} />
      <Tabs.Screen name="map" options={{ title: 'Map', tabBarIcon: tabIcon('map') }} />
      <Tabs.Screen
        name="about"
        options={{ title: 'About', tabBarIcon: tabIcon('information-circle') }}
      />
    </Tabs>
  );
}
