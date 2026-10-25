import Ionicons from '@expo/vector-icons/Ionicons';
import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { useRef, useState } from 'react';
import { Alert, Image, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { NOTE_LIMIT } from '../../api/types';
import { AddressEntry } from '../../components/AddressEntry';
import { LANGUAGES, deviceLanguage } from '../../languages';
import { GeoFix, describeFix, locateHere, photoLocation } from '../../location';
import { colors } from '../../theme';

type LocationState =
  | { kind: 'idle' }
  | { kind: 'locating' }
  | { kind: 'denied' }
  | { kind: 'failed' }
  | { kind: 'ready'; fix: GeoFix }
  | { kind: 'address'; address: string };

const CAMERA_OPTIONS: ImagePicker.ImagePickerOptions = { mediaTypes: ['images'], quality: 0.9 };
const LIBRARY_OPTIONS: ImagePicker.ImagePickerOptions = { ...CAMERA_OPTIONS, exif: true };

function locationText(state: LocationState) {
  switch (state.kind) {
    case 'locating':
      return 'Finding your location…';
    case 'denied':
      return 'Location is off. Enter the address instead.';
    case 'failed':
      return "Couldn't get your location. Enter the address instead.";
    case 'ready':
      return describeFix(state.fix);
    case 'address':
      return `${state.address} · address you entered`;
    default:
      return null;
  }
}

export default function CaptureScreen() {
  const [photo, setPhoto] = useState<ImagePicker.ImagePickerAsset | null>(null);
  const [location, setLocation] = useState<LocationState>({ kind: 'idle' });
  const [language, setLanguage] = useState(deviceLanguage);
  const [note, setNote] = useState('');
  const [editing, setEditing] = useState(false);
  const picking = useRef(false);

  async function locate(asset: ImagePicker.ImagePickerAsset | null) {
    setEditing(false);
    setLocation({ kind: 'locating' });
    try {
      const fromPhoto = asset ? await photoLocation(asset.exif) : null;
      if (fromPhoto) {
        setLocation({ kind: 'ready', fix: fromPhoto });
        return;
      }
      const fix = await locateHere();
      setLocation(fix === 'denied' ? { kind: 'denied' } : { kind: 'ready', fix });
    } catch {
      setLocation({ kind: 'failed' });
    }
  }

  async function takePhoto() {
    if (picking.current) {
      return;
    }
    picking.current = true;
    try {
      const permission = await ImagePicker.requestCameraPermissionsAsync();
      if (!permission.granted) {
        Alert.alert('Camera access is off', 'Turn it on in Settings, or choose a photo from your library.');
        return;
      }
      const result = await ImagePicker.launchCameraAsync(CAMERA_OPTIONS);
      if (!result.canceled) {
        setPhoto(result.assets[0]);
        locate(null);
      }
    } catch {
      Alert.alert('Camera unavailable', 'Choose a photo from your library instead.');
    } finally {
      picking.current = false;
    }
  }

  async function choosePhoto() {
    if (picking.current) {
      return;
    }
    picking.current = true;
    try {
      const result = await ImagePicker.launchImageLibraryAsync(LIBRARY_OPTIONS);
      if (!result.canceled) {
        setPhoto(result.assets[0]);
        locate(result.assets[0]);
      }
    } catch {
      Alert.alert('Photo library unavailable', 'Try again, or take a photo instead.');
    } finally {
      picking.current = false;
    }
  }

  function identify() {
    if (!photo || blockedReason) {
      return;
    }
    const fix = location.kind === 'ready' ? location.fix : null;
    const typedOnly = location.kind === 'address' ? location.address : null;
    router.navigate({
      pathname: '/result',
      params: {
        uri: photo.uri,
        key: photo.assetId ?? photo.fileName ?? photo.uri,
        language,
        note: note.trim(),
        ...(fix
          ? { lat: String(fix.lat), lng: String(fix.lng), address: fix.address ?? '', source: fix.source }
          : {}),
        ...(typedOnly ? { address: typedOnly, source: 'typed' } : {}),
      },
    });
  }

  const where = locationText(location);
  const located = location.kind === 'ready' || location.kind === 'address';
  const blockedReason = !photo
    ? 'Take or choose a photo first.'
    : location.kind === 'locating'
      ? 'Finding the location…'
      : !located
        ? 'Enter the address above to continue.'
        : null;
  const canChange = location.kind === 'ready' || location.kind === 'address';
  const showAddressEntry = editing || location.kind === 'denied' || location.kind === 'failed';
  const currentAddress =
    location.kind === 'ready' ? location.fix.address ?? '' : location.kind === 'address' ? location.address : '';

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
          {canChange && !editing ? (
            <Pressable onPress={() => setEditing(true)} hitSlop={8}>
              <Text style={styles.change}>Change</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}

      {showAddressEntry ? (
        <AddressEntry
          key={currentAddress}
          initial={currentAddress}
          onResolved={(fix) => {
            setLocation({ kind: 'ready', fix });
            setEditing(false);
          }}
          onUseText={(address) => {
            setLocation({ kind: 'address', address });
            setEditing(false);
          }}
          onCancel={canChange ? () => setEditing(false) : undefined}
        />
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
        maxLength={NOTE_LIMIT}
        multiline
      />
      <Text style={[styles.counter, note.length >= NOTE_LIMIT && styles.counterFull]}>
        {note.length}/{NOTE_LIMIT}
      </Text>

      <Pressable
        style={[styles.button, styles.buttonPrimary, styles.identify, blockedReason && styles.buttonDisabled]}
        onPress={identify}
        disabled={!!blockedReason}
        accessibilityHint={blockedReason ?? undefined}
      >
        <Text style={styles.buttonPrimaryText}>Identify the problem</Text>
      </Pressable>
      {blockedReason ? <Text style={styles.blocked}>{blockedReason}</Text> : null}
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
  change: { fontSize: 15, fontWeight: '600', color: colors.accent },
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
  counter: { alignSelf: 'flex-end', fontSize: 13, color: colors.muted, marginTop: -6 },
  counterFull: { color: colors.danger, fontWeight: '600' },
  identify: { flex: 0, marginTop: 8 },
  blocked: { fontSize: 14, color: colors.muted, textAlign: 'center' },
});
