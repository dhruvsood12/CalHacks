import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { GeoFix, geocodeAddress } from '../location';
import { colors } from '../theme';

type Props = {
  initial: string;
  onResolved: (fix: GeoFix) => void;
  onUseText: (address: string) => void;
  onCancel?: () => void;
};

export function AddressEntry({ initial, onResolved, onUseText, onCancel }: Props) {
  const [text, setText] = useState(initial);
  const [status, setStatus] = useState<'idle' | 'searching' | 'not_found'>('idle');
  const address = text.trim();

  async function search() {
    if (!address) {
      return;
    }
    setStatus('searching');
    const fix = await geocodeAddress(address);
    if (fix) {
      setStatus('idle');
      onResolved(fix);
    } else {
      setStatus('not_found');
    }
  }

  return (
    <View style={styles.box}>
      <TextInput
        style={styles.input}
        value={text}
        onChangeText={(value) => {
          setText(value);
          setStatus('idle');
        }}
        placeholder="Street address, e.g. 3601 Lyon St"
        placeholderTextColor={colors.muted}
        autoCapitalize="words"
        autoCorrect={false}
        returnKeyType="search"
        onSubmitEditing={search}
      />
      {status === 'not_found' ? (
        <View style={styles.notFound}>
          <Text style={styles.error}>We couldn't find that address on the map.</Text>
          <Pressable onPress={() => onUseText(address)}>
            <Text style={styles.link}>Use it anyway</Text>
          </Pressable>
        </View>
      ) : null}
      <View style={styles.row}>
        {onCancel ? (
          <Pressable style={[styles.button, styles.secondary]} onPress={onCancel}>
            <Text style={styles.secondaryText}>Cancel</Text>
          </Pressable>
        ) : null}
        <Pressable
          style={[styles.button, styles.primary, (!address || status === 'searching') && styles.disabled]}
          onPress={search}
          disabled={!address || status === 'searching'}
        >
          {status === 'searching' ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <Text style={styles.primaryText}>Use this address</Text>
          )}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { gap: 8 },
  input: {
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 12,
    fontSize: 16,
    color: colors.text,
  },
  notFound: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, alignItems: 'center' },
  error: { fontSize: 14, color: colors.danger },
  link: { fontSize: 14, fontWeight: '600', color: colors.accent },
  row: { flexDirection: 'row', gap: 8 },
  button: { flex: 1, borderRadius: 10, paddingVertical: 12, alignItems: 'center' },
  primary: { backgroundColor: colors.accent },
  primaryText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  secondary: { backgroundColor: colors.accentSoft },
  secondaryText: { color: colors.accent, fontSize: 15, fontWeight: '600' },
  disabled: { opacity: 0.4 },
});
