// Types and helpers for the photo reading flow (Feature 2).

import { coverUrl } from './live';

export const MAX_PHOTO_BYTES = 4 * 1024 * 1024; // 4 MB

export interface PhotoCandidate {
  title: string;
  author: string | null;
  isbn: string;
  cover_url: string | null;
  edition?: string;
}

export interface PhotoLineMatched {
  read_title: string;
  read_author: string | null;
  status: 'matched';
  candidate: PhotoCandidate;
}

export interface PhotoLineAmbiguous {
  read_title: string;
  read_author: string | null;
  status: 'ambiguous';
  candidates: PhotoCandidate[];
}

export interface PhotoLineNotFound {
  read_title: string;
  read_author: string | null;
  status: 'not_found';
}

export type PhotoLine = PhotoLineMatched | PhotoLineAmbiguous | PhotoLineNotFound;

export interface PhotoReadResult {
  lines: PhotoLine[];
}

export interface PhotoReadError {
  error: 'read_failed';
}

export type PhotoReadResponse = PhotoReadResult | PhotoReadError;

export function isPhotoError(r: PhotoReadResponse): r is PhotoReadError {
  return 'error' in r;
}

/** A matched line, or an ambiguous line after the shopper has picked a candidate. */
export interface ResolvedLine {
  read_title: string;
  read_author: string | null;
  candidate: PhotoCandidate;
}

/** The photo result screen state. */
export type PhotoState =
  | { kind: 'idle' }
  | { kind: 'reading' }
  | { kind: 'oversize'; size: number }
  | { kind: 'failed' }
  | {
      kind: 'result';
      matched: ResolvedLine[];
      ambiguous: { line: PhotoLineAmbiguous; picked: PhotoCandidate | null }[];
      notFound: PhotoLineNotFound[];
    };

export function coverOf(c: PhotoCandidate): string | null {
  return coverUrl({ cover_url: c.cover_url, isbn: c.isbn });
}

export function editionLabel(e: string | undefined): string {
  if (!e) return '';
  return e.charAt(0).toUpperCase() + e.slice(1).replace(/_/g, ' ');
}
