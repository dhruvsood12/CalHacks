import abstainExample from '../../../contracts/examples/classify.response.abstain.json';
import classifyExample from '../../../contracts/examples/classify.response.json';
import contextExample from '../../../contracts/examples/context.response.json';
import { categoryInfo } from '../categories';
import { Api, Classification, CityContext, Report } from './types';

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function isUnsure(key: string) {
  let hash = 0;
  for (let i = 0; i < key.length; i++) {
    hash = (hash * 31 + key.charCodeAt(i)) | 0;
  }
  return (hash & 1) === 1;
}

export const mockApi: Api = {
  async classify(photo, location) {
    await wait(600);
    const example: Classification = isUnsure(photo.key) ? abstainExample : classifyExample;
    return { ...example, used_location: location !== null };
  },

  async context(label) {
    await wait(400);
    const example: CityContext = contextExample;
    return { ...example, label };
  },

  async report(request) {
    await wait(1200);
    const label = request.chosen_label ?? request.classification.top_k[0].label;
    const info = categoryInfo(label);
    const name = info?.display_name ?? label;
    const where = request.location?.address ? ` at ${request.location.address}` : '';
    const text = `Mock data: no Claude call was made. With the API connected, Claude writes this report about the ${name.toLowerCase()}${where} in the chosen language, with an English copy.`;
    const report: Report = {
      category: label,
      agrees_with_classifier: label === request.classification.top_k[0].label,
      agency: info?.primary_agency ?? '',
      title: `Mock report: ${name}`,
      description: text,
      title_en: `Mock report: ${name}`,
      description_en: text,
      next_steps: 'Connect the API to get a real report. Snap311 never files for you.',
      emergency: false,
      language: request.language,
      claude_model: 'mock',
    };
    return report;
  },
};
