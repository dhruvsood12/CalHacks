import { getLocales } from 'expo-localization';

export const LANGUAGES = [
  { tag: 'en', label: 'English' },
  { tag: 'es', label: 'Español' },
  { tag: 'zh-Hans', label: '中文' },
  { tag: 'fil', label: 'Filipino' },
  { tag: 'vi', label: 'Tiếng Việt' },
  { tag: 'ru', label: 'Русский' },
];

export function deviceLanguage() {
  const code = getLocales()[0]?.languageCode ?? 'en';
  if (code === 'zh') {
    return 'zh-Hans';
  }
  if (code === 'tl') {
    return 'fil';
  }
  return LANGUAGES.some((language) => language.tag === code) ? code : 'en';
}
