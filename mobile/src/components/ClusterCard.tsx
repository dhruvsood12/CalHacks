import Ionicons from '@expo/vector-icons/Ionicons';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { authorityOf, categoryInfo } from '../categories';
import { ReportCluster } from '../live';
import { colors } from '../theme';

const SOURCE_WHY = {
  photo: "From the photo's own GPS",
  gps: "Phone's GPS when the photo was taken",
  typed: 'Address the resident typed',
};

function ago(timestamp: number) {
  const minutes = Math.max(0, Math.round((Date.now() - timestamp) / 60_000));
  if (minutes < 1) {
    return 'just now';
  }
  if (minutes < 60) {
    return `${minutes} min ago`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    return `${hours} h ago`;
  }
  return `${Math.round(hours / 24)} d ago`;
}

function Why({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.whyRow}>
      <Text style={styles.whyLabel}>{label}</Text>
      <Text style={styles.whyValue}>{value}</Text>
    </View>
  );
}

export function ClusterCard({ cluster, onClose }: { cluster: ReportCluster; onClose: () => void }) {
  const report = cluster.latest;
  const authority = authorityOf(report.agency);
  const percent = Math.round(report.confidence * 100);
  const modelName = categoryInfo(report.model_label)?.display_name ?? report.model_label;
  const submitted = report.submitted_label ?? report.model_label;
  const submittedName = categoryInfo(submitted)?.display_name ?? submitted;

  const category =
    report.chosen_by === 'model'
      ? `Model's top pick, ${percent}%`
      : `Picked by the resident: ${submittedName}. Model's top guess was ${modelName}, ${percent}%`;
  const claude = report.agrees_with_classifier
    ? 'Agreed with the category'
    : `Changed it from ${submittedName} to ${report.display_name}`;
  const source =
    report.model_version === 'mock'
      ? 'Mock data: no model or Claude call was made'
      : report.model_version === 'demo-seed'
        ? 'Seeded demo report'
        : `Model ${report.model_version}`;

  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <Text style={styles.title}>{report.display_name}</Text>
        <Pressable onPress={onClose} hitSlop={12} accessibilityLabel="Close">
          <Ionicons name="close" size={22} color={colors.muted} />
        </Pressable>
      </View>

      <Text style={styles.reports}>
        {cluster.count > 1
          ? `${cluster.count} reports within 75 m · first ${ago(cluster.first_reported_at)}, latest ${ago(cluster.last_reported_at)}`
          : `Reported ${ago(cluster.last_reported_at)}`}
      </Text>
      {cluster.city_open_nearby > 0 ? (
        <Text style={styles.reports}>
          Plus {cluster.city_open_nearby} open city {cluster.city_open_nearby === 1 ? 'report' : 'reports'} nearby
        </Text>
      ) : null}

      <View style={styles.routed}>
        <View style={[styles.dot, { backgroundColor: authority.color }]} />
        <Text style={styles.routedText}>{report.agency}</Text>
      </View>

      <Text style={styles.section}>Why this agency</Text>
      <Why label="Agency" value="The usual agency for this category in SF's own 311 history" />
      <Why label="Category" value={category} />
      <Why label="Claude" value={claude} />
      <Why label="Location" value={`${SOURCE_WHY[report.location_source]}${report.address ? ` · ${report.address}` : ''}`} />
      <Text style={styles.meta}>
        {source} · report written in {report.language}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    position: 'absolute',
    left: 12,
    right: 12,
    bottom: 12,
    borderRadius: 14,
    backgroundColor: colors.background,
    padding: 16,
    gap: 6,
    shadowColor: '#000',
    shadowOpacity: 0.15,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
  header: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  title: { flex: 1, fontSize: 18, fontWeight: '700', color: colors.text },
  reports: { fontSize: 14, color: colors.text },
  routed: { flexDirection: 'row', alignItems: 'center', gap: 8, marginTop: 4 },
  dot: { width: 12, height: 12, borderRadius: 6, borderWidth: 2, borderColor: colors.background },
  routedText: { flex: 1, fontSize: 15, fontWeight: '600', color: colors.text },
  section: { fontSize: 12, fontWeight: '700', color: colors.muted, textTransform: 'uppercase', marginTop: 6 },
  whyRow: { flexDirection: 'row', gap: 8 },
  whyLabel: { width: 72, fontSize: 13, fontWeight: '600', color: colors.muted },
  whyValue: { flex: 1, fontSize: 13, color: colors.text },
  meta: { fontSize: 12, color: colors.muted, marginTop: 4 },
});
