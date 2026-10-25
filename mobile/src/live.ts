import { ConvexReactClient } from 'convex/react';
import { makeFunctionReference } from 'convex/server';
import { LocationSource } from './location';

export type NewReport = {
  category: string;
  display_name: string;
  agency: string;
  lat: number;
  lng: number;
  address: string | null;
  location_source: LocationSource;
  language: string;
  title_en: string;
  model_label: string;
  confidence: number;
  chosen_by: 'model' | 'resident';
  agrees_with_classifier: boolean;
  model_version: string;
  city_open_nearby: number;
};

export type SavedReport = NewReport & { _id: string; _creationTime: number };

export type ReportCluster = {
  id: string;
  lat: number;
  lng: number;
  count: number;
  first_reported_at: number;
  last_reported_at: number;
  city_open_nearby: number;
  latest: SavedReport;
};

const url = process.env.EXPO_PUBLIC_CONVEX_URL?.trim();

export const convex = url ? new ConvexReactClient(url, { unsavedChangesWarning: false }) : null;

export const saveReport = makeFunctionReference<'mutation', NewReport, string>('reports:save');
export const listClusters = makeFunctionReference<'query', Record<string, never>, ReportCluster[]>(
  'reports:clusters',
);
