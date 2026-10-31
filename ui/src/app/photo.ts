// Types and helpers for the photo reading flow (Feature 2).

import { coverUrl } from './live';

export const MAX_PHOTO_BYTES = 4 * 1024 * 1024; // 4 MB

// S22: a phone camera JPEG is often 3-8 MB and 4000 px. Before upload the photo is drawn at most
// PHOTO_LONG_SIDE px on its long side and sent as a JPEG at PHOTO_JPEG_QUALITY. A small photo in a
// type /photo takes is sent as it is. A HEIC the browser can decode is converted the same way.
export const PHOTO_LONG_SIDE = 2000;
export const PHOTO_JPEG_QUALITY = 0.85;
const PHOTO_SEND_AS_IS_BYTES = 1024 * 1024;
const PHOTO_TYPES = ['image/png', 'image/jpeg', 'image/webp'];

export interface PhotoUpload {
  body: Blob;
  type: string;
}

/** The photo to upload: shrunk and re-encoded when it is big, the file itself otherwise or when the
 *  browser cannot decode it (then /photo answers as before). */
export async function shrinkPhoto(file: Blob): Promise<PhotoUpload> {
  const asIs: PhotoUpload = { body: file, type: file.type || 'application/octet-stream' };
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return asIs;
  }
  try {
    const long = Math.max(bitmap.width, bitmap.height);
    if (PHOTO_TYPES.includes(file.type) && long <= PHOTO_LONG_SIDE && file.size <= PHOTO_SEND_AS_IS_BYTES) {
      return asIs;
    }
    const k = Math.min(1, PHOTO_LONG_SIDE / long);
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * k));
    canvas.height = Math.max(1, Math.round(bitmap.height * k));
    const g = canvas.getContext('2d');
    if (!g) return asIs;
    g.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const jpeg = await new Promise<Blob | null>((done) => canvas.toBlob(done, 'image/jpeg', PHOTO_JPEG_QUALITY));
    return jpeg ? { body: jpeg, type: 'image/jpeg' } : asIs;
  } finally {
    bitmap.close();
  }
}

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
