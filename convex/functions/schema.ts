import { defineSchema, defineTable } from 'convex/server';
import { v } from 'convex/values';

export const reportFields = {
  category: v.string(),
  display_name: v.string(),
  agency: v.string(),
  lat: v.number(),
  lng: v.number(),
  address: v.union(v.string(), v.null()),
  location_source: v.union(v.literal('photo'), v.literal('gps'), v.literal('typed')),
  language: v.string(),
  title_en: v.string(),
  model_label: v.string(),
  submitted_label: v.optional(v.string()),
  confidence: v.number(),
  chosen_by: v.union(v.literal('model'), v.literal('resident')),
  agrees_with_classifier: v.boolean(),
  model_version: v.string(),
  city_open_nearby: v.number(),
};

export default defineSchema({
  reports: defineTable(reportFields),
});
