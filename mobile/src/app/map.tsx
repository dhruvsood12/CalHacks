import { EmptyState } from '../components/EmptyState';

export default function MapScreen() {
  return (
    <EmptyState
      icon="map-outline"
      title="Live map"
      message="New reports appear here as they are added."
    />
  );
}
