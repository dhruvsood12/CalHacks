export type Candidate = {
  label: string;
  display_name: string;
  agency: string;
  prob: number;
};

export type Classification = {
  model_version: string;
  top_k: Candidate[];
  abstain: boolean;
  abstain_threshold: number;
  latency_ms: number;
  used_location: boolean;
};

export type NearbyReport = {
  service_request_id: string;
  distance_m: number;
  requested_at: string;
  days_open: number;
  status: string;
  address?: string | null;
};

export type FixTime = {
  median_days: number;
  p75_days: number;
  n: number;
  scope: string;
};

export type CityContext = {
  label: string;
  address: string | null;
  nearby_open: NearbyReport[];
  fix_time: FixTime | null;
  data_as_of: string;
};

export type ReportLocation = {
  lat: number;
  lng: number;
  address: string | null;
};

export type ReportRequest = {
  image_b64: string;
  media_type: 'image/jpeg' | 'image/png' | 'image/webp';
  classification: Classification;
  chosen_label: string | null;
  language: string;
  location: ReportLocation | null;
  user_note: string | null;
};

export type Report = {
  category: string;
  agrees_with_classifier: boolean;
  agency: string;
  title: string;
  description: string;
  title_en: string;
  description_en: string;
  next_steps: string;
  emergency: boolean;
  language: string;
  claude_model: string;
};

export type GeoPoint = {
  lat: number;
  lng: number;
};

export type PreparedPhoto = {
  uri: string;
  base64: string;
  key: string;
};

export interface Api {
  classify(photo: PreparedPhoto, location: GeoPoint | null): Promise<Classification>;
  context(label: string, location: GeoPoint): Promise<CityContext>;
  report(request: ReportRequest): Promise<Report>;
}
