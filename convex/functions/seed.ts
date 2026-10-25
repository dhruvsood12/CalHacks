import { ConvexError, v } from 'convex/values';
import categories from '../../contracts/categories.json';
import { internalMutation } from './_generated/server';

export const SEED_MODEL_VERSION = 'demo-seed';
const TEST_MODEL_VERSIONS = [SEED_MODEL_VERSION, 'live-check', 'mock', 'stub'];

type SeedReport = {
  category: string;
  display_name: string;
  agency: string;
  lat: number;
  lng: number;
  address: string | null;
  location_source: 'photo' | 'gps' | 'typed';
  language: string;
  title_en: string;
  model_label: string;
  submitted_label: string;
  confidence: number;
  chosen_by: 'model' | 'resident';
  agrees_with_classifier: boolean;
  city_open_nearby: number;
};

const POTHOLE = {
  category: 'pavement_defect',
  display_name: 'Pothole or street pavement damage',
  agency: 'PW - Street and Sewer Repair',
  title_en: 'Large pothole in the street',
};

const REPORTS: SeedReport[] = [
  {
    ...POTHOLE,
    lat: 37.76512,
    lng: -122.41948,
    address: '2001 Mission St',
    location_source: 'photo',
    language: 'es',
    model_label: 'pavement_defect',
    submitted_label: 'pavement_defect',
    confidence: 0.88,
    chosen_by: 'model',
    agrees_with_classifier: true,
    city_open_nearby: 1,
  },
  {
    ...POTHOLE,
    lat: 37.76531,
    lng: -122.41931,
    address: '2009 Mission St',
    location_source: 'gps',
    language: 'zh-Hans',
    model_label: 'pavement_defect',
    submitted_label: 'pavement_defect',
    confidence: 0.79,
    chosen_by: 'model',
    agrees_with_classifier: true,
    city_open_nearby: 1,
  },
  {
    ...POTHOLE,
    lat: 37.76488,
    lng: -122.41962,
    address: '1995 Mission St',
    location_source: 'typed',
    language: 'en',
    model_label: 'sidewalk_defect',
    submitted_label: 'pavement_defect',
    confidence: 0.41,
    chosen_by: 'resident',
    agrees_with_classifier: true,
    city_open_nearby: 1,
  },
  {
    category: 'blocked_sidewalk',
    display_name: 'Blocked sidewalk',
    agency: 'MTA - Access/Mobility Services Received',
    lat: 37.7793,
    lng: -122.4193,
    address: '1 Dr Carlton B Goodlett Pl',
    location_source: 'photo',
    language: 'fil',
    title_en: 'Sidewalk blocked by construction fencing',
    model_label: 'blocked_sidewalk',
    submitted_label: 'blocked_sidewalk',
    confidence: 0.72,
    chosen_by: 'model',
    agrees_with_classifier: true,
    city_open_nearby: 0,
  },
  {
    category: 'streetlight',
    display_name: 'Streetlight out or damaged',
    agency: 'PUC - Streetlights',
    lat: 37.7841,
    lng: -122.4076,
    address: '901 Market St',
    location_source: 'gps',
    language: 'vi',
    title_en: 'Streetlight out at the corner',
    model_label: 'streetlight',
    submitted_label: 'streetlight',
    confidence: 0.91,
    chosen_by: 'model',
    agrees_with_classifier: true,
    city_open_nearby: 2,
  },
  {
    category: 'graffiti',
    display_name: 'Graffiti',
    agency: 'PW - Street and Environmental Services',
    lat: 37.7609,
    lng: -122.4350,
    address: '500 Castro St',
    location_source: 'photo',
    language: 'en',
    title_en: 'Graffiti on a utility box',
    model_label: 'graffiti',
    submitted_label: 'graffiti',
    confidence: 0.95,
    chosen_by: 'model',
    agrees_with_classifier: true,
    city_open_nearby: 0,
  },
  {
    category: 'traffic_sign',
    display_name: 'Damaged or missing traffic sign',
    agency: 'MTA - Sign Shop',
    lat: 37.7735,
    lng: -122.4645,
    address: '700 Fulton St',
    location_source: 'typed',
    language: 'ru',
    title_en: 'Stop sign knocked down',
    model_label: 'traffic_sign',
    submitted_label: 'traffic_sign',
    confidence: 0.83,
    chosen_by: 'model',
    agrees_with_classifier: true,
    city_open_nearby: 0,
  },
];

const MISSION = { lat: 37.76512, lng: -122.41948 };

export const demo = internalMutation({
  args: {
    lat: v.optional(v.number()),
    lng: v.optional(v.number()),
    address: v.optional(v.string()),
    category: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const picked = args.category
      ? categories.classes.find((c: { label: string }) => c.label === args.category)
      : null;
    if (args.category && !picked) {
      throw new ConvexError(`unknown category ${args.category}`);
    }
    const dLat = (args.lat ?? MISSION.lat) - MISSION.lat;
    const dLng = (args.lng ?? MISSION.lng) - MISSION.lng;
    const moved = dLat !== 0 || dLng !== 0;
    const existing = await ctx.db.query('reports').collect();
    let removed = 0;
    for (const report of existing) {
      if (TEST_MODEL_VERSIONS.includes(report.model_version)) {
        await ctx.db.delete(report._id);
        removed += 1;
      }
    }
    for (const [index, report] of REPORTS.entries()) {
      const inCluster = index < 3;
      await ctx.db.insert('reports', {
        ...report,
        lat: inCluster ? report.lat + dLat : report.lat,
        lng: inCluster ? report.lng + dLng : report.lng,
        address: inCluster && moved ? args.address ?? null : report.address,
        ...(inCluster && picked
          ? {
              category: picked.label,
              display_name: picked.display_name,
              agency: picked.primary_agency,
              model_label: picked.label,
              submitted_label: picked.label,
              title_en: `${picked.display_name} (seeded demo report)`,
            }
          : {}),
        model_version: SEED_MODEL_VERSION,
      });
    }
    return { removed, inserted: REPORTS.length };
  },
});

export const clear = internalMutation({
  args: {},
  handler: async (ctx) => {
    const existing = await ctx.db.query('reports').collect();
    let removed = 0;
    for (const report of existing) {
      if (TEST_MODEL_VERSIONS.includes(report.model_version)) {
        await ctx.db.delete(report._id);
        removed += 1;
      }
    }
    return { removed };
  },
});
