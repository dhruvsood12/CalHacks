import { ConvexError, v } from 'convex/values';
import { Doc } from './_generated/dataModel';
import { mutation, query } from './_generated/server';
import { reportFields } from './schema';

const MAX_LIST = 500;
const DUPLICATE_RADIUS_M = 75;
const EARTH_RADIUS_M = 6_371_000;

function distanceM(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(h));
}

export const save = mutation({
  args: reportFields,
  handler: async (ctx, args) => {
    if (Math.abs(args.lat) > 90 || Math.abs(args.lng) > 180) {
      throw new ConvexError('lat/lng out of range');
    }
    if (args.confidence < 0 || args.confidence > 1) {
      throw new ConvexError('confidence must be between 0 and 1');
    }
    if (args.title_en.length > 200 || (args.address?.length ?? 0) > 200) {
      throw new ConvexError('text field is too long');
    }
    if (args.city_open_nearby < 0) {
      throw new ConvexError('city_open_nearby must not be negative');
    }
    return await ctx.db.insert('reports', args);
  },
});

export const listRecent = query({
  args: { limit: v.optional(v.number()) },
  handler: async (ctx, { limit }) => {
    const n = Math.max(1, Math.min(limit ?? 200, MAX_LIST));
    return await ctx.db.query('reports').order('desc').take(n);
  },
});

type Cluster = {
  id: string;
  lat: number;
  lng: number;
  count: number;
  first_reported_at: number;
  last_reported_at: number;
  city_open_nearby: number;
  latest: Doc<'reports'>;
};

export const clusters = query({
  args: {},
  handler: async (ctx) => {
    const recent = await ctx.db.query('reports').order('desc').take(MAX_LIST);
    const result: Cluster[] = [];
    for (const report of recent) {
      const home = result.find(
        (cluster) =>
          cluster.latest.category === report.category && distanceM(cluster, report) <= DUPLICATE_RADIUS_M,
      );
      if (home) {
        home.count += 1;
        home.first_reported_at = report._creationTime;
        home.city_open_nearby = Math.max(home.city_open_nearby, report.city_open_nearby);
        continue;
      }
      result.push({
        id: report._id,
        lat: report.lat,
        lng: report.lng,
        count: 1,
        first_reported_at: report._creationTime,
        last_reported_at: report._creationTime,
        city_open_nearby: report.city_open_nearby,
        latest: report,
      });
    }
    return result;
  },
});
