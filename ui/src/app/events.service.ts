import { Injectable, InjectionToken, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { Progress } from './live';

export type LiveEvent =
  | { type: 'progress'; progress: Progress }
  | { type: 'solution'; payload: any }
  | { type: 'error'; message: string };

export interface SourceLike {
  readyState?: number;
  addEventListener(name: string, fn: (e: { data: string }) => void): void;
  onerror: ((e: unknown) => void) | null;
  close(): void;
}

export const EVENT_SOURCE = new InjectionToken<(url: string) => SourceLike>('EVENT_SOURCE', {
  providedIn: 'root',
  factory: () => (url: string) => new EventSource(url) as unknown as SourceLike,
});

export function liveUrl(isbn13: string, itemId: string, title: string, author?: string | null, listing?: string | null): string {
  const q = new URLSearchParams({ source: 'live', isbn13, item_id: itemId, title });
  if (author) q.set('author', author);
  if (listing) q.set('listing', listing);
  return '/events?' + q.toString();
}

/** Streams GET /events?source=live: read_progress lines, then one solution. */
@Injectable({ providedIn: 'root' })
export class EventsService {
  private readonly make = inject(EVENT_SOURCE);

  open(url: string): Observable<LiveEvent> {
    return new Observable<LiveEvent>((sub) => {
      const src = this.make(url);
      let done = false;
      const finish = () => {
        done = true;
        src.close();
        sub.complete();
      };
      const parse = (data: string): any => {
        try {
          return JSON.parse(data);
        } catch {
          return null;
        }
      };
      src.addEventListener('read_progress', (e) => {
        const d = parse(e.data);
        if (d) sub.next({ type: 'progress', progress: d as Progress });
      });
      src.addEventListener('solution', (e) => {
        const d = parse(e.data);
        if (d) sub.next({ type: 'solution', payload: d });
        finish();
      });
      src.addEventListener('error', (e) => {
        // A named "error" event carries JSON; a network drop carries nothing.
        const d = e && typeof e.data === 'string' ? parse(e.data) : null;
        if (!d) return;
        sub.next({ type: 'error', message: d.error || 'The read failed.' });
        finish();
      });
      src.onerror = () => {
        if (done) return;
        // EventSource would reconnect and start the live reads again. Stop instead.
        sub.next({ type: 'error', message: 'The connection dropped.' });
        finish();
      };
      return () => {
        if (!done) src.close();
      };
    });
  }
}
