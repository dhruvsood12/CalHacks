import { ConvexError, v } from 'convex/values';
import { mutation, query } from './_generated/server';
import { reportFields } from './schema';

const MAX_LIST = 500;

export const save = mutation({
  args: reportFields,
  handler: async (ctx, args) => {
    if (Math.abs(args.lat) > 90 || Math.abs(args.lng) > 180) {
      throw new ConvexError('lat/lng out of range');
    }
    if (args.confidence < 0 || args.confidence > 1) {
      throw new ConvexError('confidence must be between 0 and 1');
    }
    if (args.title_en.length > 200) {
      throw new ConvexError('title_en is too long');
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
