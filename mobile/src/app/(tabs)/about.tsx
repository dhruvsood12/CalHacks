import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { AUTHORITY_COUNT, CATEGORY_COUNT } from '../../categories';
import { colors } from '../../theme';

const STEPS = [
  {
    title: 'You take a photo',
    body: 'The location comes from the photo itself or your phone. No menus, no pin to drop.',
  },
  {
    title: 'A vision model names the problem',
    body: `It was trained on real San Francisco 311 photo reports and picks one of ${CATEGORY_COUNT} categories, with the agency that usually handles it. When it isn't confident, it says so and shows its best guesses instead of guessing.`,
  },
  {
    title: 'We check what the city already knows',
    body: 'Open reports of the same kind nearby, and how long similar problems usually take to fix.',
  },
  {
    title: 'Claude writes the report',
    body: 'In your language, with an English copy for the city. Claude double-checks the category and flags anything dangerous.',
  },
  {
    title: 'You file it',
    body: 'We never file for you. Copy the report into sf311.org or the SF311 app.',
  },
];

export default function AboutScreen() {
  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content}>
      <Text style={styles.heading}>How it works</Text>
      {STEPS.map((step, index) => (
        <View key={step.title} style={styles.step}>
          <Text style={styles.stepNumber}>{index + 1}</Text>
          <View style={styles.stepText}>
            <Text style={styles.stepTitle}>{step.title}</Text>
            <Text style={styles.body}>{step.body}</Text>
          </View>
        </View>
      ))}

      <View style={styles.card}>
        <Text style={styles.cardTitle}>How accurate is it?</Text>
        <Text style={styles.body}>
          Results from a sealed test set appear here once the final evaluation has run. Every number is read
          from the team's published results file, never typed in.
        </Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>The live map</Text>
        <Text style={styles.body}>
          Each pin is one place, colored by the agency that usually handles it ({AUTHORITY_COUNT} groups). A
          number on a pin counts reports of the same kind within 75 m. Tap a pin to see why it went to that
          agency and where its location came from.
        </Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>What we keep</Text>
        <Text style={styles.body}>
          The map stores the category, agency, location, an English title and how the decision was made. Your
          photo is never stored.
        </Text>
      </View>

      <Text style={styles.footer}>
        Data: DataSF 311 Cases. Built at Cal Hacks 13.0. Not affiliated with the City of San Francisco.
      </Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: { padding: 16, gap: 14 },
  heading: { fontSize: 22, fontWeight: '700', color: colors.text },
  step: { flexDirection: 'row', gap: 12 },
  stepNumber: {
    width: 26,
    height: 26,
    borderRadius: 13,
    backgroundColor: colors.accentSoft,
    color: colors.accent,
    fontWeight: '700',
    textAlign: 'center',
    lineHeight: 26,
    overflow: 'hidden',
  },
  stepText: { flex: 1, gap: 2 },
  stepTitle: { fontSize: 16, fontWeight: '600', color: colors.text },
  body: { fontSize: 15, color: colors.text, lineHeight: 21 },
  card: { borderRadius: 12, backgroundColor: colors.surface, padding: 14, gap: 6 },
  cardTitle: { fontSize: 17, fontWeight: '700', color: colors.text },
  footer: { fontSize: 12, color: colors.muted, marginTop: 4 },
});
