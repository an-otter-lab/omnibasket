import { TestBed } from '@angular/core/testing';
import { EVENT_SOURCE, EventsService, LiveEvent, SourceLike, liveUrl } from './events.service';

class FakeSource implements SourceLike {
  handlers: Record<string, ((e: { data: string }) => void)[]> = {};
  onerror: ((e: unknown) => void) | null = null;
  closed = false;
  constructor(readonly url: string) {}
  addEventListener(name: string, fn: (e: { data: string }) => void): void {
    (this.handlers[name] ||= []).push(fn);
  }
  close(): void {
    this.closed = true;
  }
  emit(name: string, data: unknown): void {
    for (const fn of this.handlers[name] || []) fn({ data: JSON.stringify(data) });
  }
}

describe('EventsService (/events live read)', () => {
  let source: FakeSource;
  let service: EventsService;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [{ provide: EVENT_SOURCE, useValue: (url: string) => (source = new FakeSource(url)) }],
    });
    service = TestBed.inject(EventsService);
  });

  it('builds the live URL from the contract', () => {
    const url = liveUrl('9781526605412', 'book-9781526605412', 'Harry Potter');
    expect(url).toBe('/events?source=live&isbn13=9781526605412&item_id=book-9781526605412&title=Harry+Potter');
  });

  it('listens to read_progress and emits lines in arrival order, then the solution', () => {
    const got: LiveEvent[] = [];
    let completed = false;
    service.open('/events?source=live').subscribe({ next: (e) => got.push(e), complete: () => (completed = true) });
    const lines = ['Reading Libris…', 'Reading eMAG…', "eMAG couldn't be read, skipped", 'Libris: ok'];
    for (const message of lines) source.emit('read_progress', { store_id: 'x', isbn13: '1', status: 'reading', message });
    source.emit('solution', { live_offers: [] });
    expect(got.map((e) => (e.type === 'progress' ? e.progress.message : e.type))).toEqual([...lines, 'solution']);
    expect(completed).toBeTrue();
    expect(source.closed).toBeTrue();
  });

  it('turns a named error event into one error and closes', () => {
    const got: LiveEvent[] = [];
    service.open('/events?source=live').subscribe((e) => got.push(e));
    source.emit('error', { error: 'solve failed' });
    expect(got).toEqual([{ type: 'error', message: 'solve failed' }]);
    expect(source.closed).toBeTrue();
  });

  it('stops on a dropped connection instead of letting EventSource re-run the reads', () => {
    const got: LiveEvent[] = [];
    service.open('/events?source=live').subscribe((e) => got.push(e));
    source.onerror!({});
    expect(got.length).toBe(1);
    expect(got[0].type).toBe('error');
    expect(source.closed).toBeTrue();
  });

  it('closes the stream when the caller unsubscribes', () => {
    const sub = service.open('/events?source=live').subscribe();
    sub.unsubscribe();
    expect(source.closed).toBeTrue();
  });
});
