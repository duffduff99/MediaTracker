export type Role = "admin" | "editor" | "viewer";

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  prefs: Prefs;
  created_at: string;
  last_login_at: string | null;
}

export interface Prefs {
  hidden_columns?: string[];
  theme?: "system" | "light" | "dark";
  physical_only?: boolean;
}

export interface Category {
  id: number;
  name: string;
  has_artist: boolean;
  sort_order: number;
}

export interface Format {
  id: number;
  category_id: number; // default category
  category_ids: number[]; // every category the format is used for (default first)
  name: string;
  color: string;
  physical: boolean;
  sort_order: number;
}

export type FieldType = "text" | "longtext" | "number" | "boolean" | "select" | "multiselect" | "date";

export interface Field {
  id: number;
  key: string;
  label: string;
  type: FieldType;
  options: string[];
  applies_all: boolean;
  format_ids: number[];
  sort_order: number;
}

export interface Meta {
  categories: Category[];
  formats: Format[];
  fields: Field[];
  lookups_enabled: boolean;
  plex_format_id: number | null;
}

export type CustomValue = string | number | boolean | string[];

export interface Item {
  id: number;
  title_id: number;
  format_id: number;
  barcode: string | null;
  box_set_id: number | null;
  box_set_name: string | null;
  box_set_barcode: string | null;
  notes: string | null;
  custom: Record<string, CustomValue>;
  added_by: string | null;
  source_ref: string | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
  title: string;
  sort_title: string;
  artist: string | null;
  year: number | null;
  category_id: number;
}

export interface TitleDetail {
  id: number;
  category_id: number;
  name: string;
  artist: string | null;
  year: number | null;
  items: Item[];
  box_sets: { id: number; name: string; count: number }[];
}

export interface TitleHit {
  id: number;
  name: string;
  year: number | null;
  artist: string | null;
  category_id: number;
  formats: string[];
}

export interface BoxSet {
  id: number;
  name: string;
  barcode: string | null;
  notes: string | null;
  count?: number;
  items?: Item[];
}

export interface WishItem {
  id: number;
  text: string;
  done: number;
  added_by: string | null;
  created_at: string;
}

export interface SearchResult {
  titles: { title_id: number; name: string; year: number | null; artist: string | null; category_id: number; items: Item[] }[];
  box_sets: BoxSet[];
  wishlist: WishItem[];
  total_items: number;
  total_titles?: number;
}

export interface Stats {
  items: number;
  titles: number;
  multi_format_titles: number;
  formats_in_use: number;
  box_sets: number;
  wishlist_open: number;
  by_format: { format_id: number; count: number }[];
  by_category: { category_id: number; count: number }[];
  recent: Item[];
}

export interface LookupCandidate {
  title: string | null;
  artist: string | null;
  year: number | null;
  custom: Record<string, CustomValue>;
  source: string;
  url: string | null;
  detail: string | null;
}

export interface LookupAttempt {
  source: string;
  status: "found" | "not_found" | "skipped" | "rate_limited" | "unreachable" | "auth" | "error";
  message: string;
  cached: boolean;
}

export interface LookupResult {
  barcode: string;
  suggestion: LookupCandidate | null;
  candidates: LookupCandidate[];
  product_name: string | null;
  warnings: string[];
  attempts: LookupAttempt[];
  existing_titles: TitleHit[];
}

export interface IntegrationKey {
  key: string;
  label: string;
  help: string;
  url: string;
  env: string;
  set: boolean;
  from_env: boolean;
  hint: string | null;
}

export interface Integrations {
  lookups_enabled: boolean;
  keys: IntegrationKey[];
  hosts: string[];
}

export interface PlexSection {
  key: string;
  title: string;
  type: "movie" | "show";
}

export interface PlexConfig {
  url: string;
  token_set: boolean;
  token_hint: string | null;
  sections: PlexSection[];
  format_id: number | null;
  auto_sync: boolean;
  configured: boolean;
  last_sync: { at: string; scheduled: boolean; plex_titles?: number; counts?: Record<string, number>; warnings?: string[]; error?: string } | null;
}

export interface PlexReport {
  dry_run: boolean;
  plex_titles: number;
  format: string;
  counts: Record<string, number>;
  lists: Record<string, string[]>;
  warnings: string[];
  unchanged: number;
}
