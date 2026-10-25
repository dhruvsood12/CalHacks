import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import { PreparedPhoto } from './api';

const MAX_SIDE = 1280;

export async function preparePhoto(uri: string, key: string): Promise<PreparedPhoto> {
  const image = await ImageManipulator.manipulate(uri, {
    maxWidth: MAX_SIDE,
    maxHeight: MAX_SIDE,
  }).renderAsync();
  const saved = await image.saveAsync({ format: SaveFormat.JPEG, compress: 0.8, base64: true });
  return { uri: saved.uri, base64: saved.base64 ?? '', key };
}
