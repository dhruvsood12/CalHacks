import * as Clipboard from 'expo-clipboard';
import { useLocalSearchParams } from 'expo-router';
import { ReactNode, useEffect, useState } from 'react';
import { ActivityIndicator, Image, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import {
  Candidate,
  CityContext,
  Classification,
  GeoPoint,
  PreparedPhoto,
  NOTE_LIMIT,
  Report,
  ReportRequest,
  api,
  usingMock,
} from '../api';
import { categoryInfo } from '../categories';
import { AddToMap } from '../components/AddToMap';
import { NewReport, convex } from '../live';
import { LocationSource, SOURCE_LABEL } from '../location';
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
  source?: LocationSource;
};

type Duplicate = 'confirm' | 'file' | null;

type ContextState = 'idle' | 'loading' | 'ready' | 'error' | 'skipped';

function clampNote(userNote: string, extras: string[]) {
  const extra = extras.join(' ');
  const room = NOTE_LIMIT - (extra ? extra.length + 1 : 0);
  const note = userNote.length > room ? `${userNote.slice(0, Math.max(0, room - 1))}…` : userNote;
  return [note, extra].filter(Boolean).join(' ').slice(0, NOTE_LIMIT);
}

function days(n: number) {
  const rounded = Math.max(1, Math.round(n));
  return `${rounded} ${rounded === 1 ? 'day' : 'days'}`;
}

function reportText(report: Report, candidate: Candidate | undefined, address: string | undefined, location: GeoPoint | null) {
  const where = [address, location ? `${location.lat.toFixed(5)}, ${location.lng.toFixed(5)}` : null]
    .filter(Boolean)
    .join(' · ');
  return [
    report.title_en,
    '',
    report.description_en,
    '',
    `Category: ${candidate?.display_name ?? report.category}`,
    report.agency ? `Usually handled by: ${report.agency}` : null,
    where ? `Location: ${where}` : null,
  ]
    .filter((line) => line !== null)
    .join('\n');
}

function mapDraft(
  report: Report,
  classification: Classification,
  selected: string,
  location: GeoPoint,
  address: string | undefined,
  source: LocationSource,
  context: CityContext | null,
): NewReport {
  const top = classification.top_k[0];
  const reported = classification.top_k.find((candidate) => candidate.label === report.category);
  return {
    category: report.category,
    display_name: categoryInfo(report.category)?.display_name ?? reported?.display_name ?? report.category,
    agency: report.agency,
    lat: location.lat,
    lng: location.lng,
    address: address || null,
    location_source: source,
    language: report.language,
    title_en: report.title_en.slice(0, 200),
    model_label: top.label,
    submitted_label: selected,
    confidence: top.prob,
    chosen_by: !classification.abstain && selected === top.label ? 'model' : 'resident',
    agrees_with_classifier: report.category === selected,
    model_version: usingMock ? 'mock' : classification.model_version,
    city_open_nearby: context?.nearby_open.length ?? 0,
  };
}

function MapAction({ draft, blocked }: { draft: NewReport | null; blocked: string | null }) {
  if (!convex) {
    return null;
  }
  if (!draft) {
    return <Text style={styles.muted}>{blocked}</Text>;
  }
  return <AddToMap draft={draft} />;
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

function ReportCard({
  report,
  copyText,
  mapAction,
}: {
  report: Report;
  copyText: string;
  mapAction: ReactNode;
}) {
  const [showEnglish, setShowEnglish] = useState(false);
  const [copied, setCopied] = useState(false);
  const translated = report.language !== 'en';

  useEffect(() => {
    if (!copied) {
      return;
    }
    const timer = setTimeout(() => setCopied(false), 2500);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy() {
    await Clipboard.setStringAsync(copyText);
    setCopied(true);
  }

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
      <Pressable style={styles.primaryButton} onPress={copy} accessibilityLabel="Copy the English report for the city">
        <Text style={styles.primaryButtonText}>{copied ? 'Copied' : 'Copy report (English, for the city)'}</Text>
      </Pressable>
      <Pressable style={styles.secondaryButton} onPress={() => Linking.openURL('https://sf311.org')}>
        <Text style={styles.secondaryButtonText}>Open sf311.org</Text>
      </Pressable>
      {mapAction}
      <Text style={styles.muted}>We never file for you. Paste the report into sf311.org or the SF311 app.</Text>
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
  const [contextState, setContextState] = useState<ContextState>('idle');
  const [contextError, setContextError] = useState<string | null>(null);
  const [contextAttempt, setContextAttempt] = useState(0);
  const [classifyAttempt, setClassifyAttempt] = useState(0);
  const [duplicate, setDuplicate] = useState<Duplicate>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [reportState, setReportState] = useState<'idle' | 'loading' | 'error'>('idle');
  const [reportError, setReportError] = useState<string | null>(null);

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
  }, [params.uri, classifyAttempt]);

  useEffect(() => {
    setContext(null);
    setContextError(null);
    setDuplicate(null);
    setReport(null);
    if (!selected || !location) {
      setContextState('idle');
      return;
    }
    setContextState('loading');
    let cancelled = false;
    api
      .context(selected, location)
      .then((result) => {
        if (!cancelled) {
          setContext(result);
          setContextState('ready');
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setContextError(e instanceof Error ? e.message : String(e));
          setContextState('error');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selected, contextAttempt]);

  async function writeReport() {
    if (!photo || !classification || !selected) {
      return;
    }
    const extras: string[] = [];
    if (!location && params.address) {
      extras.push(`Location: ${params.address}.`);
    }
    const nearest = context?.nearby_open[0];
    if (duplicate === 'confirm' && nearest) {
      extras.push(`Also seen on ${today()}. Same problem as open case ${nearest.service_request_id}.`);
    }
    const userNote = clampNote(params.note ?? '', extras);
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
    setReportError(null);
    try {
      setReport(await api.report(request));
      setReportState('idle');
    } catch (e) {
      setReportError(e instanceof Error ? e.message : String(e));
      setReportState('error');
    }
  }

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.cardTitle}>Couldn't identify this photo</Text>
        <Text style={styles.body}>{error}</Text>
        <Pressable
          style={[styles.primaryButton, styles.retry]}
          onPress={() => {
            setError(null);
            setClassifyAttempt((n) => n + 1);
          }}
        >
          <Text style={styles.primaryButtonText}>Retry</Text>
        </Pressable>
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
  const contextSettled = !location || contextState === 'ready' || contextState === 'skipped';
  const canWrite = !!selected && contextSettled && (!hasDuplicate || duplicate !== null);
  const writeLabel = needsChoice
    ? 'Pick a category first'
    : contextState === 'loading'
      ? 'Checking for existing reports…'
      : contextState === 'error' || (hasDuplicate && !duplicate)
        ? 'Choose an option above'
        : reportState === 'error'
          ? 'Try writing the report again'
          : 'Write my report';

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content} contentInsetAdjustmentBehavior="automatic">
      {usingMock ? <Text style={styles.mockBadge}>Mock data</Text> : null}
      <View style={styles.row}>
        <Image source={{ uri: params.uri }} style={styles.thumb} />
        <View style={styles.summary}>
          <Text style={styles.muted}>
            {params.address
              ? `${params.address}${params.source ? ` · ${SOURCE_LABEL[params.source]}` : ''}`
              : 'No location'}
          </Text>
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
      {contextState === 'loading' ? (
        <View style={[styles.card, styles.row]}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.body}>Checking for existing reports nearby…</Text>
        </View>
      ) : null}
      {contextState === 'error' ? (
        <View style={[styles.card, styles.unsure]}>
          <Text style={styles.cardTitle}>Couldn't check whether this was already reported</Text>
          <Text style={styles.muted}>{contextError}</Text>
          <View style={styles.row}>
            <Pressable style={styles.smallButton} onPress={() => setContextAttempt((n) => n + 1)}>
              <Text style={styles.smallButtonText}>Retry</Text>
            </Pressable>
            <Pressable style={styles.smallButton} onPress={() => setContextState('skipped')}>
              <Text style={styles.smallButtonText}>Continue without the check</Text>
            </Pressable>
          </View>
        </View>
      ) : null}
      {contextState === 'skipped' ? (
        <Text style={styles.muted}>Duplicate check skipped. This report may already be open with the city.</Text>
      ) : null}
      {selected && !location ? (
        <Text style={styles.muted}>No map location, so we couldn't check for existing reports.</Text>
      ) : null}

      {report ? (
        <ReportCard
          report={report}
          copyText={reportText(
            report,
            classification.top_k.find((candidate) => candidate.label === report.category) ??
              classification.top_k.find((candidate) => candidate.label === selected),
            params.address,
            location,
          )}
          mapAction={
            <MapAction
              draft={
                location && selected && report.category !== 'not_a_311_issue'
                  ? mapDraft(report, classification, selected, location, params.address, params.source ?? 'gps', context)
                  : null
              }
              blocked={
                report.category === 'not_a_311_issue'
                  ? "This doesn't look like a city issue, so it isn't added to the map."
                  : 'Add a location with a map point to put this on the live map.'
              }
            />
          }
        />
      ) : (
        <Pressable
          style={[styles.primaryButton, (!canWrite || reportState === 'loading') && styles.disabled]}
          onPress={writeReport}
          disabled={!canWrite || reportState === 'loading'}
        >
          {reportState === 'loading' ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.primaryButtonText}>{writeLabel}</Text>
          )}
        </Pressable>
      )}
      {reportState === 'error' ? (
        <View style={[styles.card, styles.unsure]}>
          <Text style={styles.cardTitle}>The report writer didn't answer</Text>
          {reportError ? <Text style={styles.muted}>{reportError}</Text> : null}
          <Text style={styles.body}>
            Your photo, category and choices are kept. Try again, or use the category and agency above to file on
            sf311.org.
          </Text>
        </View>
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
  retry: { alignSelf: 'stretch', marginTop: 8 },
});
