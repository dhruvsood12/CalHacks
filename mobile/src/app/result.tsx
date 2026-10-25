import { useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Image, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import {
  Candidate,
  CityContext,
  Classification,
  GeoPoint,
  PreparedPhoto,
  Report,
  ReportRequest,
  api,
  usingMock,
} from '../api';
import { preparePhoto } from '../photo';
import { colors } from '../theme';

type Params = {
  uri: string;
  key: string;
  language: string;
  note?: string;
  lat?: string;
  lng?: string;
  address?: string;
};

type Duplicate = 'confirm' | 'file' | null;

function days(n: number) {
  const rounded = Math.max(1, Math.round(n));
  return `${rounded} ${rounded === 1 ? 'day' : 'days'}`;
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function CandidateRow({
  candidate,
  selected,
  onPress,
}: {
  candidate: Candidate;
  selected: boolean;
  onPress: () => void;
}) {
  const percent = Math.round(candidate.prob * 100);
  return (
    <Pressable
      onPress={onPress}
      style={[styles.candidate, selected && styles.candidateSelected]}
      accessibilityRole="radio"
      accessibilityState={{ selected }}
    >
      <View style={styles.candidateHeader}>
        <Text style={styles.candidateName}>{candidate.display_name}</Text>
        <Text style={styles.candidatePercent}>{percent}%</Text>
      </View>
      <Text style={styles.candidateAgency}>Usually handled by {candidate.agency}</Text>
      <View style={styles.barTrack}>
        <View style={[styles.barFill, { width: `${percent}%` }]} />
      </View>
    </Pressable>
  );
}

function ContextCard({
  context,
  duplicate,
  onDuplicate,
}: {
  context: CityContext;
  duplicate: Duplicate;
  onDuplicate: (choice: Duplicate) => void;
}) {
  const nearest = context.nearby_open[0];
  const fix = context.fix_time;
  return (
    <View style={styles.card}>
      {nearest ? (
        <View style={styles.duplicate}>
          <Text style={styles.cardTitle}>Already reported?</Text>
          <Text style={styles.body}>
            Someone reported this {days(nearest.days_open)} ago, {Math.round(nearest.distance_m)} m away. Still{' '}
            {nearest.status.toLowerCase()}.
          </Text>
          <View style={styles.row}>
            <Pressable
              style={[styles.smallButton, duplicate === 'confirm' && styles.smallButtonSelected]}
              onPress={() => onDuplicate('confirm')}
            >
              <Text style={[styles.smallButtonText, duplicate === 'confirm' && styles.smallButtonTextSelected]}>
                Add mine as confirmation
              </Text>
            </Pressable>
            <Pressable
              style={[styles.smallButton, duplicate === 'file' && styles.smallButtonSelected]}
              onPress={() => onDuplicate('file')}
            >
              <Text style={[styles.smallButtonText, duplicate === 'file' && styles.smallButtonTextSelected]}>
                File anyway
              </Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <Text style={styles.body}>No open reports of this kind nearby.</Text>
      )}
      {fix ? (
        <Text style={styles.body}>
          Similar issues are typically fixed in about {days(fix.median_days)} (most within {days(fix.p75_days)}).{' '}
          <Text style={styles.muted}>{fix.scope}</Text>
        </Text>
      ) : null}
    </View>
  );
}

function ReportCard({ report }: { report: Report }) {
  const [showEnglish, setShowEnglish] = useState(false);
  const translated = report.language !== 'en';

  if (report.emergency) {
    return (
      <View style={[styles.card, styles.emergency]}>
        <Text style={styles.emergencyTitle}>This looks dangerous. Call 911.</Text>
        <Text style={styles.body}>{report.description}</Text>
        <Pressable style={styles.emergencyButton} onPress={() => Linking.openURL('tel:911')}>
          <Text style={styles.emergencyButtonText}>Call 911</Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{report.title}</Text>
      <Text style={styles.body}>{report.description}</Text>
      <Text style={styles.body}>{report.next_steps}</Text>
      {translated ? (
        <Pressable onPress={() => setShowEnglish((value) => !value)}>
          <Text style={styles.link}>{showEnglish ? 'Hide' : 'Show'} the English copy for the city</Text>
        </Pressable>
      ) : null}
      {translated && showEnglish ? (
        <View style={styles.english}>
          <Text style={styles.englishTitle}>{report.title_en}</Text>
          <Text style={styles.body}>{report.description_en}</Text>
        </View>
      ) : null}
      <Pressable style={styles.secondaryButton} onPress={() => Linking.openURL('https://sf311.org')}>
        <Text style={styles.secondaryButtonText}>Open sf311.org</Text>
      </Pressable>
      <Text style={styles.muted}>We never file for you. Copy this into sf311.org or the SF311 app.</Text>
    </View>
  );
}

export default function ResultScreen() {
  const params = useLocalSearchParams<Params>();
  const location: GeoPoint | null =
    params.lat && params.lng ? { lat: Number(params.lat), lng: Number(params.lng) } : null;

  const [photo, setPhoto] = useState<PreparedPhoto | null>(null);
  const [classification, setClassification] = useState<Classification | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [context, setContext] = useState<CityContext | null>(null);
  const [duplicate, setDuplicate] = useState<Duplicate>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [reportState, setReportState] = useState<'idle' | 'loading' | 'error'>('idle');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const prepared = await preparePhoto(params.uri, params.key);
        const result = await api.classify(prepared, location);
        if (cancelled) {
          return;
        }
        setPhoto(prepared);
        setClassification(result);
        setSelected(result.abstain ? null : result.top_k[0].label);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params.uri]);

  useEffect(() => {
    setContext(null);
    setDuplicate(null);
    setReport(null);
    if (!selected || !location) {
      return;
    }
    let cancelled = false;
    api
      .context(selected, location)
      .then((result) => {
        if (!cancelled) {
          setContext(result);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [selected]);

  async function writeReport() {
    if (!photo || !classification || !selected) {
      return;
    }
    const notes = [params.note ?? ''];
    const nearest = context?.nearby_open[0];
    if (duplicate === 'confirm' && nearest) {
      notes.push(`Also seen on ${today()}. Same problem as open case ${nearest.service_request_id}.`);
    }
    const userNote = notes.filter(Boolean).join(' ');
    const request: ReportRequest = {
      image_b64: photo.base64,
      media_type: 'image/jpeg',
      classification,
      chosen_label: selected,
      language: params.language,
      location: location ? { ...location, address: params.address || null } : null,
      user_note: userNote || null,
    };
    setReportState('loading');
    try {
      setReport(await api.report(request));
      setReportState('idle');
    } catch {
      setReportState('error');
    }
  }

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.cardTitle}>Couldn't identify this photo</Text>
        <Text style={styles.body}>{error}</Text>
      </View>
    );
  }

  if (!classification) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={colors.accent} />
        <Text style={styles.muted}>Looking at your photo…</Text>
      </View>
    );
  }

  const needsChoice = classification.abstain && !selected;
  const hasDuplicate = (context?.nearby_open.length ?? 0) > 0;
  const canWrite = !!selected && (!hasDuplicate || duplicate !== null);

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content} contentInsetAdjustmentBehavior="automatic">
      {usingMock ? <Text style={styles.mockBadge}>Mock data</Text> : null}
      <View style={styles.row}>
        <Image source={{ uri: params.uri }} style={styles.thumb} />
        <View style={styles.summary}>
          <Text style={styles.muted}>{params.address || 'No location'}</Text>
          {classification.used_location ? <Text style={styles.muted}>Location helped the prediction</Text> : null}
        </View>
      </View>

      {classification.abstain ? (
        <View style={[styles.card, styles.unsure]}>
          <Text style={styles.cardTitle}>Not sure. Here are my best guesses.</Text>
          <Text style={styles.body}>Pick the one that fits your photo.</Text>
        </View>
      ) : null}

      {classification.top_k.map((candidate) => (
        <CandidateRow
          key={candidate.label}
          candidate={candidate}
          selected={candidate.label === selected}
          onPress={() => setSelected(candidate.label)}
        />
      ))}

      {context ? <ContextCard context={context} duplicate={duplicate} onDuplicate={setDuplicate} /> : null}

      {report ? (
        <ReportCard report={report} />
      ) : (
        <Pressable
          style={[styles.primaryButton, (!canWrite || reportState === 'loading') && styles.disabled]}
          onPress={writeReport}
          disabled={!canWrite || reportState === 'loading'}
        >
          {reportState === 'loading' ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.primaryButtonText}>
              {needsChoice ? 'Pick a category first' : 'Write my report'}
            </Text>
          )}
        </Pressable>
      )}
      {reportState === 'error' ? (
        <Text style={styles.errorText}>The report writer is unavailable. Your category and agency above are still right to use.</Text>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: { padding: 16, gap: 12 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 },
  row: { flexDirection: 'row', gap: 12, alignItems: 'center' },
  thumb: { width: 72, height: 96, borderRadius: 8, backgroundColor: colors.surface },
  summary: { flex: 1, gap: 4 },
  mockBadge: {
    alignSelf: 'flex-start',
    backgroundColor: colors.warningSoft,
    color: colors.warning,
    fontSize: 12,
    fontWeight: '700',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 6,
    overflow: 'hidden',
  },
  card: { borderRadius: 12, backgroundColor: colors.surface, padding: 14, gap: 8 },
  cardTitle: { fontSize: 17, fontWeight: '700', color: colors.text },
  body: { fontSize: 15, color: colors.text, lineHeight: 21 },
  muted: { fontSize: 13, color: colors.muted },
  unsure: { backgroundColor: colors.warningSoft },
  candidate: { borderRadius: 12, borderWidth: 1.5, borderColor: colors.border, padding: 14, gap: 6 },
  candidateSelected: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  candidateHeader: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  candidateName: { flex: 1, fontSize: 16, fontWeight: '600', color: colors.text },
  candidatePercent: { fontSize: 16, fontWeight: '600', color: colors.accent },
  candidateAgency: { fontSize: 13, color: colors.muted },
  barTrack: { height: 6, borderRadius: 3, backgroundColor: colors.border, overflow: 'hidden' },
  barFill: { height: 6, borderRadius: 3, backgroundColor: colors.accent },
  duplicate: { gap: 8 },
  smallButton: {
    flex: 1,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: colors.accent,
    paddingVertical: 8,
    paddingHorizontal: 6,
    alignItems: 'center',
  },
  smallButtonSelected: { backgroundColor: colors.accent },
  smallButtonText: { color: colors.accent, fontSize: 14, fontWeight: '600', textAlign: 'center' },
  smallButtonTextSelected: { color: '#fff' },
  primaryButton: { borderRadius: 10, paddingVertical: 14, alignItems: 'center', backgroundColor: colors.accent },
  primaryButtonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  disabled: { opacity: 0.4 },
  secondaryButton: { borderRadius: 10, paddingVertical: 12, alignItems: 'center', backgroundColor: colors.accentSoft },
  secondaryButtonText: { color: colors.accent, fontSize: 16, fontWeight: '600' },
  link: { color: colors.accent, fontSize: 15, fontWeight: '600' },
  english: { borderTopWidth: 1, borderTopColor: colors.border, paddingTop: 8, gap: 4 },
  englishTitle: { fontSize: 15, fontWeight: '700', color: colors.text },
  emergency: { backgroundColor: colors.dangerSoft },
  emergencyTitle: { fontSize: 18, fontWeight: '800', color: colors.danger },
  emergencyButton: { borderRadius: 10, paddingVertical: 14, alignItems: 'center', backgroundColor: colors.danger },
  emergencyButtonText: { color: '#fff', fontSize: 17, fontWeight: '700' },
  errorText: { fontSize: 14, color: colors.danger },
});
