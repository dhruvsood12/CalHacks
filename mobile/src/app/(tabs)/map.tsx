import { useQuery } from 'convex/react';
import { useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import MapView, { Marker } from 'react-native-maps';
import { AUTHORITIES, authorityOf } from '../../categories';
import { ClusterCard } from '../../components/ClusterCard';
import { EmptyState } from '../../components/EmptyState';
import { ReportCluster, convex, listClusters } from '../../live';
import { colors } from '../../theme';

const SAN_FRANCISCO = {
  latitude: 37.7599,
  longitude: -122.4348,
  latitudeDelta: 0.13,
  longitudeDelta: 0.1,
};

function Pin({ cluster, selected }: { cluster: ReportCluster; selected: boolean }) {
  const color = authorityOf(cluster.latest.agency).color;
  const size = cluster.count > 1 ? 26 : 18;
  return (
    <View style={styles.pinBox}>
      <View
        style={[
          styles.pin,
          { width: size, height: size, borderRadius: size / 2, backgroundColor: color },
          selected && styles.pinSelected,
        ]}
      />
      {cluster.count > 1 ? (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{cluster.count}</Text>
        </View>
      ) : null}
    </View>
  );
}

function Legend({ clusters }: { clusters: ReportCluster[] }) {
  const reports = clusters.reduce((total, cluster) => total + cluster.count, 0);
  return (
    <View style={styles.legend}>
      <Text style={styles.legendTitle}>
        {reports} {reports === 1 ? 'report' : 'reports'} · {clusters.length}{' '}
        {clusters.length === 1 ? 'place' : 'places'}
      </Text>
      <View style={styles.legendItems}>
        {AUTHORITIES.map((authority) => (
          <View key={authority.key} style={styles.legendRow}>
            <View style={[styles.legendDot, { backgroundColor: authority.color }]} />
            <Text style={styles.legendText}>{authority.short}</Text>
          </View>
        ))}
      </View>
      <Text style={styles.legendHint}>Number on a pin = reports within 75 m</Text>
    </View>
  );
}

function LiveMap() {
  const clusters = useQuery(listClusters, {});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = clusters?.find((cluster) => cluster.id === selectedId) ?? null;

  return (
    <View style={styles.screen}>
      <MapView
        style={StyleSheet.absoluteFill}
        initialRegion={SAN_FRANCISCO}
        onPress={(event) => {
          if (event.nativeEvent.action !== 'marker-press') {
            setSelectedId(null);
          }
        }}
      >
        {clusters?.map((cluster) => (
          <Marker
            key={cluster.id}
            coordinate={{ latitude: cluster.lat, longitude: cluster.lng }}
            onPress={() => setSelectedId(cluster.id)}
            accessibilityLabel={`${cluster.latest.display_name}, ${cluster.count} reports`}
          >
            <Pin cluster={cluster} selected={cluster.id === selectedId} />
          </Marker>
        ))}
      </MapView>
      {clusters ? <Legend clusters={clusters} /> : null}
      {clusters === undefined ? (
        <View style={styles.loading}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.legendText}>Connecting to the live map…</Text>
        </View>
      ) : null}
      {selected ? <ClusterCard cluster={selected} onClose={() => setSelectedId(null)} /> : null}
    </View>
  );
}

export default function MapScreen() {
  if (!convex) {
    return (
      <EmptyState
        icon="map-outline"
        title="Live map isn't connected"
        message="Set EXPO_PUBLIC_CONVEX_URL in mobile/.env to the Convex deployment URL, then restart Expo."
      />
    );
  }
  return <LiveMap />;
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  pinBox: { padding: 6 },
  pin: { borderWidth: 2, borderColor: '#ffffff' },
  pinSelected: { borderWidth: 3, borderColor: colors.text },
  badge: {
    position: 'absolute',
    top: 0,
    right: 0,
    minWidth: 18,
    height: 18,
    paddingHorizontal: 4,
    borderRadius: 9,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: { fontSize: 11, fontWeight: '700', color: colors.text },
  legend: {
    position: 'absolute',
    top: 8,
    left: 8,
    right: 8,
    borderRadius: 12,
    backgroundColor: 'rgba(255,255,255,0.94)',
    paddingHorizontal: 10,
    paddingVertical: 8,
    gap: 4,
  },
  legendItems: { flexDirection: 'row', flexWrap: 'wrap', columnGap: 12, rowGap: 4 },
  legendTitle: { fontSize: 13, fontWeight: '700', color: colors.text },
  legendRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  legendDot: { width: 10, height: 10, borderRadius: 5 },
  legendText: { fontSize: 12, color: colors.text },
  legendHint: { fontSize: 11, color: colors.muted, marginTop: 2 },
  loading: {
    position: 'absolute',
    top: '45%',
    alignSelf: 'center',
    flexDirection: 'row',
    gap: 8,
    alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.94)',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
});
