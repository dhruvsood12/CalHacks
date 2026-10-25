import abstainExample from '../../../contracts/examples/classify.response.abstain.json';
import classifyExample from '../../../contracts/examples/classify.response.json';
import contextExample from '../../../contracts/examples/context.response.json';
import reportExample from '../../../contracts/examples/report.response.json';
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

  async report() {
    await wait(1200);
    const example: Report = reportExample;
    return example;
  },
};
