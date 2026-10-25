import { useMutation } from 'convex/react';
import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text } from 'react-native';
import { NewReport, saveReport } from '../live';
import { colors } from '../theme';

export function AddToMap({ draft }: { draft: NewReport }) {
  const save = useMutation(saveReport);
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');

  async function add() {
    setState('saving');
    try {
      await save(draft);
      setState('saved');
    } catch {
      setState('error');
    }
  }

  if (state === 'saved') {
    return (
      <Pressable style={[styles.button, styles.saved]} onPress={() => router.navigate('/map')}>
        <Text style={styles.savedText}>On the live map · See it</Text>
      </Pressable>
    );
  }

  return (
    <>
      <Pressable style={[styles.button, styles.add]} onPress={add} disabled={state === 'saving'}>
        {state === 'saving' ? (
          <ActivityIndicator color={colors.accent} />
        ) : (
          <Text style={styles.addText}>Add to map</Text>
        )}
      </Pressable>
      {state === 'error' ? <Text style={styles.error}>Couldn't reach the live map. Try again.</Text> : null}
    </>
  );
}

const styles = StyleSheet.create({
  button: { borderRadius: 10, paddingVertical: 12, alignItems: 'center' },
  add: { backgroundColor: colors.accentSoft },
  addText: { color: colors.accent, fontSize: 16, fontWeight: '600' },
  saved: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.accent },
  savedText: { color: colors.accent, fontSize: 16, fontWeight: '600' },
  error: { fontSize: 14, color: colors.danger },
});
