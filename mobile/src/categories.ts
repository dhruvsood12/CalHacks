import categories from '../../contracts/categories.json';
import { colors } from './theme';

type Category = { label: string; display_name: string; primary_agency: string };

const byLabel = new Map<string, Category>(
  (categories.classes as Category[]).map((category) => [category.label, category]),
);

export const CATEGORY_COUNT = byLabel.size;

export function categoryInfo(label: string) {
  return byLabel.get(label) ?? null;
}

export type Authority = { key: string; name: string; short: string; color: string };

export const AUTHORITIES: Authority[] = [
  { key: 'PW', name: 'Public Works', short: 'Public Works', color: colors.authorityPW },
  { key: 'MTA', name: 'SFMTA', short: 'SFMTA', color: colors.authorityMTA },
  { key: 'PUC', name: 'SF Public Utilities', short: 'SFPUC', color: colors.authorityPUC },
  { key: 'OTHER', name: 'Other (incl. Healthy Streets)', short: 'Other', color: colors.authorityOther },
];

export const AUTHORITY_COUNT = AUTHORITIES.length;

export function authorityOf(agency: string): Authority {
  const prefix = agency.split(' - ')[0];
  return AUTHORITIES.find((authority) => authority.key === prefix) ?? AUTHORITIES[AUTHORITIES.length - 1];
}
