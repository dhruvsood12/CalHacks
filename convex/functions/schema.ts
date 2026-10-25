import { defineSchema, defineTable } from 'convex/server';
import { v } from 'convex/values';

export const reportFields = {
  category: v.string(),
  display_name: v.string(),
  agency: v.string(),
  lat: v.number(),
  lng: v.number(),
  language: v.string(),
  title_en: v.string(),
  confidence: v.number(),
};

export default defineSchema({
  reports: defineTable(reportFields),
});
