import Ionicons from '@expo/vector-icons/Ionicons';
import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { useState } from 'react';
import { Alert, Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { LANGUAGES, deviceLanguage } from '../../languages';
import { GeoFix, describeFix, locateHere } from '../../location';
import { colors } from '../../theme';

type LocationState =
  | { kind: 'idle' }
  | { kind: 'locating' }
  | { kind: 'denied' }
  | { kind: 'failed' }
  | { kind: 'ready'; fix: GeoFix };

const PICKER_OPTIONS: ImagePicker.ImagePickerOptions = { mediaTypes: ['images'], quality: 0.9 };

function locationText(state: LocationState) {
  switch (state.kind) {
    case 'locating':
      return 'Finding your location…';
    case 'denied':
      return 'Location is off. Add the address in the note below.';
    case 'failed':
      return "Couldn't get your location. Add the address in the note below.";
    case 'ready':
      return describeFix(state.fix);
    default:
      return null;
  }
}

export default function CaptureScreen() {
  const [photo, setPhoto] = useState<ImagePicker.ImagePickerAsset | null>(null);
  const [location, setLocation] = useState<LocationState>({ kind: 'idle' });
  const [language, setLanguage] = useState(deviceLanguage);
  const [note, setNote] = useState('');

  async function locate() {
    setLocation({ kind: 'locating' });
    try {
      const fix = await locateHere();
      setLocation(fix === 'denied' ? { kind: 'denied' } : { kind: 'ready', fix });
    } catch {
      setLocation({ kind: 'failed' });
    }
  }

  async function takePhoto() {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Camera access is off', 'Turn it on in Settings, or choose a photo from your library.');
      return;
    }
    try {
      const result = await ImagePicker.launchCameraAsync(PICKER_OPTIONS);
      if (!result.canceled) {
        setPhoto(result.assets[0]);
        locate();
      }
    } catch {
      Alert.alert('Camera unavailable', 'Choose a photo from your library instead.');
    }
  }

  async function choosePhoto() {
    const result = await ImagePicker.launchImageLibraryAsync(PICKER_OPTIONS);
    if (!result.canceled) {
      setPhoto(result.assets[0]);
      locate();
    }
  }

  function identify() {
    if (!photo) {
      return;
    }
    const fix = location.kind === 'ready' ? location.fix : null;
    router.navigate({
      pathname: '/result',
      params: {
        uri: photo.uri,
        key: photo.assetId ?? photo.fileName ?? photo.uri,
        language,
        note: note.trim(),
        ...(fix ? { lat: String(fix.lat), lng: String(fix.lng), address: fix.address ?? '' } : {}),
      },
    });
  }

  const where = locationText(location);

  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      {photo ? (
        <Image source={{ uri: photo.uri }} style={styles.preview} resizeMode="cover" />
      ) : (
        <View style={[styles.preview, styles.placeholder]}>
          <Text style={styles.placeholderTitle}>Report a street problem</Text>
          <Text style={styles.placeholderText}>Take or choose a photo. We find the location for you.</Text>
        </View>
      )}

      <View style={styles.row}>
        <Pressable style={[styles.button, styles.buttonPrimary]} onPress={takePhoto}>
          <Text style={styles.buttonPrimaryText}>Take photo</Text>
        </Pressable>
        <Pressable style={[styles.button, styles.buttonSecondary]} onPress={choosePhoto}>
          <Text style={styles.buttonSecondaryText}>Choose photo</Text>
        </Pressable>
      </View>

      {where ? (
        <View style={styles.locationRow}>
          <Ionicons name="location" size={18} color={colors.accent} />
          <Text style={styles.location}>{where}</Text>
        </View>
      ) : null}

      <Text style={styles.label}>Report language</Text>
      <View style={styles.chips}>
        {LANGUAGES.map((option) => {
          const selected = option.tag === language;
          return (
            <Pressable
              key={option.tag}
              onPress={() => setLanguage(option.tag)}
              style={[styles.chip, selected && styles.chipSelected]}
              accessibilityRole="button"
              accessibilityState={{ selected }}
            >
              <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{option.label}</Text>
            </Pressable>
          );
        })}
      </View>

      <Text style={styles.label}>Anything to add? (optional)</Text>
      <TextInput
        style={styles.note}
        value={note}
        onChangeText={setNote}
        placeholder="e.g. Deep pothole in the right lane"
        placeholderTextColor={colors.muted}
        maxLength={500}
        multiline
      />

      <Pressable
        style={[styles.button, styles.buttonPrimary, styles.identify, !photo && styles.buttonDisabled]}
        onPress={identify}
        disabled={!photo}
      >
        <Text style={styles.buttonPrimaryText}>Identify the problem</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: { padding: 16, gap: 12 },
  preview: { width: '100%', height: 300, borderRadius: 12, backgroundColor: colors.surface },
  placeholder: { alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  placeholderTitle: { fontSize: 20, fontWeight: '700', color: colors.text, textAlign: 'center' },
  placeholderText: { fontSize: 15, color: colors.muted, textAlign: 'center' },
  row: { flexDirection: 'row', gap: 12 },
  button: { flex: 1, borderRadius: 10, paddingVertical: 14, alignItems: 'center' },
  buttonPrimary: { backgroundColor: colors.accent },
  buttonPrimaryText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  buttonSecondary: { backgroundColor: colors.accentSoft },
  buttonSecondaryText: { color: colors.accent, fontSize: 16, fontWeight: '600' },
  buttonDisabled: { opacity: 0.4 },
  locationRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  location: { flex: 1, fontSize: 15, color: colors.text },
  label: { fontSize: 13, fontWeight: '600', color: colors.muted, textTransform: 'uppercase', marginTop: 4 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: { borderRadius: 16, borderWidth: 1, borderColor: colors.border, paddingHorizontal: 12, paddingVertical: 6 },
  chipSelected: { backgroundColor: colors.accent, borderColor: colors.accent },
  chipText: { fontSize: 15, color: colors.text },
  chipTextSelected: { color: '#fff' },
  note: {
    minHeight: 72,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 12,
    fontSize: 16,
    color: colors.text,
    textAlignVertical: 'top',
  },
  identify: { flex: 0, marginTop: 8 },
});
