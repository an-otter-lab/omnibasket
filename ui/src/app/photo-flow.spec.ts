import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { Subject } from 'rxjs';
import { AppComponent } from './app.component';
import { PhotoReadResponse } from './photo';
import { EventsService, LiveEvent } from './events.service';
import { BasketService } from './basket.service';

describe('Photo flow (Feature 2)', () => {
  let component: AppComponent;
  let fixture: ComponentFixture<AppComponent>;
  let httpMock: HttpTestingController;
  let eventsService: jasmine.SpyObj<EventsService>;

  beforeEach(async () => {
    localStorage.clear();
    window.location.hash = '';
    const eventsSpy = jasmine.createSpyObj('EventsService', ['open']);
    
    await TestBed.configureTestingModule({
      imports: [HttpClientTestingModule, AppComponent],
      providers: [{ provide: EventsService, useValue: eventsSpy }],
    }).compileComponents();

    eventsService = TestBed.inject(EventsService) as jasmine.SpyObj<EventsService>;
    httpMock = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(AppComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
    window.location.hash = '';
  });

  describe('matched lines join the basket', () => {
    it('should add matched lines to basket and navigate to photo result', fakeAsync(() => {
      const response: PhotoReadResponse = {
        lines: [
          {
            read_title: 'The Very Hungry Caterpillar',
            read_author: 'Eric Carle',
            status: 'matched',
            candidate: {
              title: 'The Very Hungry Caterpillar',
              author: 'Eric Carle',
              isbn: '9780141367941',
              cover_url: 'https://covers.openlibrary.org/b/isbn/9780141367941-M.jpg',
            },
          },
        ],
      };

      component.onPhotoEvent({ kind: 'read', response });
      tick();

      expect(component.photoState.kind).toBe('result');
      if (component.photoState.kind === 'result') {
        expect(component.photoState.matched.length).toBe(1);
        expect(component.photoState.matched[0].candidate.isbn).toBe('9780141367941');
        expect(component.photoState.ambiguous.length).toBe(0);
        expect(component.photoState.notFound.length).toBe(0);
      }
    }));

    it('should open parallel live streams for all matched lines', fakeAsync(() => {
      const response: PhotoReadResponse = {
        lines: [
          {
            read_title: 'The Very Hungry Caterpillar',
            read_author: 'Eric Carle',
            status: 'matched',
            candidate: {
              title: 'The Very Hungry Caterpillar',
              author: 'Eric Carle',
              isbn: '9780141367941',
              cover_url: 'https://covers.openlibrary.org/b/isbn/9780141367941-M.jpg',
            },
          },
        ],
      };

      component.onPhotoEvent({ kind: 'read', response });
      tick();

      const mockSubject = new Subject<LiveEvent>();
      eventsService.open.and.returnValue(mockSubject.asObservable());

      component.onPhotoContinue();
      tick();

      expect(eventsService.open).toHaveBeenCalledTimes(1);
      expect(component.photoState.kind).toBe('idle');
    }));
  });

  describe('ambiguous lines show pick list', () => {
    it('should display ambiguous lines with candidates', fakeAsync(() => {
      const response: PhotoReadResponse = {
        lines: [
          {
            read_title: 'Dune',
            read_author: null,
            status: 'ambiguous',
            candidates: [
              {
                title: 'Dune',
                author: 'Frank Herbert',
                isbn: '9780441172719',
                cover_url: 'https://covers.openlibrary.org/b/isbn/9780441172719-M.jpg',
              },
              {
                title: 'Dune',
                author: 'Brian Herbert',
                isbn: '9780765312891',
                cover_url: 'https://covers.openlibrary.org/b/isbn/9780765312891-M.jpg',
              },
            ],
          },
        ],
      };

      component.onPhotoEvent({ kind: 'read', response });
      tick();

      expect(component.photoState.kind).toBe('result');
      if (component.photoState.kind === 'result') {
        expect(component.photoState.matched.length).toBe(0);
        expect(component.photoState.ambiguous.length).toBe(1);
        expect(component.photoState.ambiguous[0].line.read_title).toBe('Dune');
        expect(component.photoState.ambiguous[0].line.candidates.length).toBe(2);
        expect(component.photoState.ambiguous[0].picked).toBeNull();
      }
    }));

    it('should allow picking a candidate from ambiguous line', fakeAsync(() => {
      const response: PhotoReadResponse = {
        lines: [
          {
            read_title: 'Dune',
            read_author: null,
            status: 'ambiguous',
            candidates: [
              {
                title: 'Dune',
                author: 'Frank Herbert',
                isbn: '9780441172719',
                cover_url: 'https://covers.openlibrary.org/b/isbn/9780441172719-M.jpg',
              },
              {
                title: 'Dune',
                author: 'Brian Herbert',
                isbn: '9780765312891',
                cover_url: 'https://covers.openlibrary.org/b/isbn/9780765312891-M.jpg',
              },
            ],
          },
        ],
      };

      component.onPhotoEvent({ kind: 'read', response });
      tick();

      component.onPhotoPick({ index: 0, candidate: response.lines[0].status === 'ambiguous' ? response.lines[0].candidates[0] : (null as any) });
      tick();

      if (component.photoState.kind === 'result') {
        expect(component.photoState.ambiguous[0].picked).not.toBeNull();
        expect(component.photoState.ambiguous[0].picked?.isbn).toBe('9780441172719');
      }
    }));

    it('should include picked ambiguous lines in continue flow', fakeAsync(() => {
      const response: PhotoReadResponse = {
        lines: [
          {
            read_title: 'Dune',
            read_author: null,
            status: 'ambiguous',
            candidates: [
              {
                title: 'Dune',
                author: 'Frank Herbert',
                isbn: '9780441172719',
                cover_url: 'https://covers.openlibrary.org/b/isbn/9780441172719-M.jpg',
              },
            ],
          },
        ],
      };

      component.onPhotoEvent({ kind: 'read', response });
      tick();

      component.onPhotoPick({ index: 0, candidate: response.lines[0].status === 'ambiguous' ? response.lines[0].candidates[0] : (null as any) });
      tick();

      const mockSubject = new Subject<LiveEvent>();
      eventsService.open.and.returnValue(mockSubject.asObservable());

      component.onPhotoContinue();
      tick();

      expect(eventsService.open).toHaveBeenCalledTimes(1);
    }));
  });

  describe('unmatched lines list', () => {
    it('should display unmatched lines under not found', fakeAsync(() => {
      const response: PhotoReadResponse = {
        lines: [
          {
            read_title: 'Unknown Book',
            read_author: 'Unknown Author',
            status: 'not_found',
          },
        ],
      };

      component.onPhotoEvent({ kind: 'read', response });
      tick();

      expect(component.photoState.kind).toBe('result');
      if (component.photoState.kind === 'result') {
        expect(component.photoState.matched.length).toBe(0);
        expect(component.photoState.ambiguous.length).toBe(0);
        expect(component.photoState.notFound.length).toBe(1);
        expect(component.photoState.notFound[0].read_title).toBe('Unknown Book');
        expect(component.photoState.notFound[0].read_author).toBe('Unknown Author');
      }
    }));

    it('should not open streams for not found lines', fakeAsync(() => {
      const response: PhotoReadResponse = {
        lines: [
          {
            read_title: 'The Very Hungry Caterpillar',
            read_author: 'Eric Carle',
            status: 'matched',
            candidate: {
              title: 'The Very Hungry Caterpillar',
              author: 'Eric Carle',
              isbn: '9780141367941',
              cover_url: 'https://covers.openlibrary.org/b/isbn/9780141367941-M.jpg',
            },
          },
          {
            read_title: 'Unknown Book',
            read_author: 'Unknown Author',
            status: 'not_found',
          },
        ],
      };

      component.onPhotoEvent({ kind: 'read', response });
      tick();

      const mockSubject = new Subject<LiveEvent>();
      eventsService.open.and.returnValue(mockSubject.asObservable());

      component.onPhotoContinue();
      tick();

      expect(eventsService.open).toHaveBeenCalledTimes(1);
    }));
  });

  describe('read failure', () => {
    it('should show error message when photo read fails', fakeAsync(() => {
      component.onPhotoEvent({ kind: 'read', response: { error: 'read_failed' } });
      tick();

      expect(component.photoState.kind).toBe('failed');
      expect(component.basket.size).toBe(0);
    }));

    it('should leave basket untouched on read failure', fakeAsync(() => {
      component.basketSvc.addFromLive({}, '9780000000001', 'existing-book'); component.basketSvc.items[0].id = 'existing-book';
      component.onPhotoEvent({ kind: 'read', response: { error: 'read_failed' } });
      tick();

      expect(component.photoState.kind).toBe('failed');
      expect(component.basket.size).toBe(1);
      expect(component.basket.has('existing-book')).toBeTrue();
    }));

    it('should show error message on fetch error', fakeAsync(() => {
      component.onPhotoEvent({ kind: 'error' });
      tick();

      expect(component.photoState.kind).toBe('failed');
      expect(component.basket.size).toBe(0);
    }));
  });

  describe('oversize message', () => {
    it('should show oversize message when photo exceeds 4 MB', fakeAsync(() => {
      const size = 5 * 1024 * 1024;
      component.onPhotoEvent({ kind: 'oversize', size });
      tick();

      expect(component.photoState.kind).toBe('oversize');
      if (component.photoState.kind === 'oversize') {
        expect(component.photoState.size).toBe(size);
      }
      expect(component.photoOversizeText).toContain('5.0 MB');
    }));

    it('should not open streams on oversize', fakeAsync(() => {
      const size = 5 * 1024 * 1024;
      component.onPhotoEvent({ kind: 'oversize', size });
      tick();

      expect(eventsService.open).not.toHaveBeenCalled();
      expect(component.basket.size).toBe(0);
    }));
  });

  describe('three matched lines join basket with one solve', () => {
    it('should add all three matched lines to basket and run one solve', fakeAsync(() => {
      const response: PhotoReadResponse = {
        lines: [
          {
            read_title: 'The Very Hungry Caterpillar',
            read_author: 'Eric Carle',
            status: 'matched',
            candidate: {
              title: 'The Very Hungry Caterpillar',
              author: 'Eric Carle',
              isbn: '9780141367941',
              cover_url: 'https://covers.openlibrary.org/b/isbn/9780141367941-M.jpg',
            },
          },
          {
            read_title: 'Matilda',
            read_author: 'Roald Dahl',
            status: 'matched',
            candidate: {
              title: 'Matilda',
              author: 'Roald Dahl',
              isbn: '9780141369365',
              cover_url: 'https://covers.openlibrary.org/b/isbn/9780141369365-M.jpg',
            },
          },
          {
            read_title: 'The Gruffalo',
            read_author: 'Julia Donaldson',
            status: 'matched',
            candidate: {
              title: 'The Gruffalo',
              author: 'Julia Donaldson',
              isbn: '9781035028399',
              cover_url: 'https://covers.openlibrary.org/b/isbn/9781035028399-M.jpg',
            },
          },
        ],
      };

      component.onPhotoEvent({ kind: 'read', response });
      tick();

      const subject1 = new Subject<LiveEvent>();
      const subject2 = new Subject<LiveEvent>();
      const subject3 = new Subject<LiveEvent>();
      eventsService.open.and.returnValues(
        subject1.asObservable(),
        subject2.asObservable(),
        subject3.asObservable()
      );

      const solveSpy = spyOn(component, 'refresh').and.returnValue(Promise.resolve());

      component.onPhotoContinue();
      tick();

      expect(eventsService.open).toHaveBeenCalledTimes(3);

      const mockPayload1 = {
        books: [{ item_id: 'book-9780141367941', title: 'The Very Hungry Caterpillar', isbn13: '9780141367941', edition_pin: null, editions: [], assigned_store_id: null, shops: [] }],
        shops: [],
        cheapest: { status: 'ranked', reason: null, total_cents: 1000, books_subtotal_cents: 1000, order_count: 1, orders: [], delta_vs_cheapest_cents: 0, not_ranked: [] },
        one_order: { status: 'ranked', reason: null, best_store_id: 'libris', answer: null, per_book_delta: [], shops: [] },
        custom: null,
        edition: { pins: {}, unknown_pins: [], status: 'possible', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
        failed_reads: [],
        live_offers: [],
        currency: 'RON',
        cached: false,
        read_at_range: { oldest: null, newest: null },
        degraded: null,
      };

      const mockPayload2 = {
        books: [{ item_id: 'book-9780141369365', title: 'Matilda', isbn13: '9780141369365', edition_pin: null, editions: [], assigned_store_id: null, shops: [] }],
        shops: [],
        cheapest: { status: 'ranked', reason: null, total_cents: 1200, books_subtotal_cents: 1200, order_count: 1, orders: [], delta_vs_cheapest_cents: 0, not_ranked: [] },
        one_order: { status: 'ranked', reason: null, best_store_id: 'libris', answer: null, per_book_delta: [], shops: [] },
        custom: null,
        edition: { pins: {}, unknown_pins: [], status: 'possible', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
        failed_reads: [],
        live_offers: [],
        currency: 'RON',
        cached: false,
        read_at_range: { oldest: null, newest: null },
        degraded: null,
      };

      const mockPayload3 = {
        books: [{ item_id: 'book-9781035028399', title: 'The Gruffalo', isbn13: '9781035028399', edition_pin: null, editions: [], assigned_store_id: null, shops: [] }],
        shops: [],
        cheapest: { status: 'ranked', reason: null, total_cents: 1100, books_subtotal_cents: 1100, order_count: 1, orders: [], delta_vs_cheapest_cents: 0, not_ranked: [] },
        one_order: { status: 'ranked', reason: null, best_store_id: 'libris', answer: null, per_book_delta: [], shops: [] },
        custom: null,
        edition: { pins: {}, unknown_pins: [], status: 'possible', reason: null, unpinned_total_cents: null, total_cents: null, delta_cents: null, not_ranked: [] },
        failed_reads: [],
        live_offers: [],
        currency: 'RON',
        cached: false,
        read_at_range: { oldest: null, newest: null },
        degraded: null,
      };

      subject1.next({ type: 'solution', payload: mockPayload1 });
      subject1.complete();
      tick();

      subject2.next({ type: 'solution', payload: mockPayload2 });
      subject2.complete();
      tick();

      subject3.next({ type: 'solution', payload: mockPayload3 });
      subject3.complete();
      tick();

      expect(component.basket.size).toBe(3);
      expect(component.basket.has('book-9780141367941')).toBeTrue();
      expect(component.basket.has('book-9780141369365')).toBeTrue();
      expect(component.basket.has('book-9781035028399')).toBeTrue();

      expect(solveSpy).toHaveBeenCalledTimes(1);
    }));
  });

  describe('photo add reads each book by its own ISBN', () => {
    const line = (title: string, author: string, isbn: string) => ({
      read_title: title, read_author: author, status: 'matched' as const,
      candidate: { title, author, isbn, cover_url: null },
    });
    const priced = (isbn: string, cents: number) => ({
      books: [{ item_id: 'book-' + isbn, isbn13: isbn, title: 't', shops: [{ store_id: 'libris', price_cents: cents, seller_certainty: 'known', edition: null, listing_url: null, read_at: null, status: 'ok' }] }],
      shops: [{ store_id: 'libris', priced: true, free_delivery_threshold_cents: 20000, delivery_cents: 1290, currency: 'RON', read_at: null }],
      live_offers: [{ store_id: 'libris', price_cents: cents, listing_url: null }],
      joined_item_id: 'book-' + isbn,
    });
    const three = [
      line('Harry Potter si piatra filozofala', 'J. K. Rowling', '9789735832940'),
      line('Micul print', 'Antoine de Saint-Exupery', '9786060339229'),
      line('The clean coder', 'Robert C. Martin', '9780137081073'),
    ];

    it('requests every line with its real ISBN, title and author, never the word photo', fakeAsync(() => {
      component.onPhotoEvent({ kind: 'read', response: { lines: three } });
      tick();
      const subjects = three.map(() => new Subject<LiveEvent>());
      eventsService.open.and.returnValues(...subjects.map((s) => s.asObservable()));
      spyOn(component, 'refresh').and.returnValue(Promise.resolve());
      component.onPhotoContinue();
      tick();
      window.dispatchEvent(new HashChangeEvent('hashchange'));
      tick();
      const urls = eventsService.open.calls.allArgs().map((a) => new URL(a[0], 'http://x'));
      expect(urls.length).toBe(3);  // no stray read for the progress route
      expect(urls.map((u) => u.searchParams.get('isbn13'))).toEqual(['9789735832940', '9786060339229', '9780137081073']);
      expect(urls.map((u) => u.searchParams.get('item_id'))).toEqual(['book-9789735832940', 'book-9786060339229', 'book-9780137081073']);
      expect(urls.map((u) => u.searchParams.get('title'))).toEqual(three.map((l) => l.candidate.title));
      expect(urls.map((u) => u.searchParams.get('author'))).toEqual(three.map((l) => l.candidate.author));
      expect(urls.every((u) => u.searchParams.get('source') === 'live' && u.searchParams.get('isbn13') !== 'photo')).toBeTrue();
    }));

    it('keeps the prices of a book already in the basket when the same ISBN comes back with no offer, and lists a book with no offer unpriced', fakeAsync(() => {
      const svc = TestBed.inject(BasketService);
      svc.addFromLive(priced('9789735832940', 5662), '9789735832940', 'Harry Potter si piatra filozofala');
      svc.addFromLive(priced('9780137081073', 27902), '9780137081073', 'The clean coder');
      component.onPhotoEvent({ kind: 'read', response: { lines: three } });
      tick();
      const subjects = three.map(() => new Subject<LiveEvent>());
      eventsService.open.and.returnValues(...subjects.map((s) => s.asObservable()));
      const refresh = spyOn(component, 'refresh').and.returnValue(Promise.resolve());
      component.onPhotoContinue();
      tick();
      subjects[0].next({ type: 'solution', payload: { books: [], shops: [], live_offers: [] } });  // already priced, nothing new
      subjects[1].next({ type: 'solution', payload: { books: [], shops: [], live_offers: [] } });  // new, no offer anywhere
      subjects[2].next({ type: 'error', message: 'read failed' });  // its read breaks
      tick();
      const byIsbn = (i: string) => svc.items.find((x) => x.isbn === i)!;
      expect(svc.items.length).toBe(3);
      expect(byIsbn('9789735832940').offers.map((o) => o.price_cents)).toEqual([5662]);
      expect(byIsbn('9780137081073').offers.map((o) => o.price_cents)).toEqual([27902]);
      expect(byIsbn('9789735832940').author).toBe('J. K. Rowling');
      expect(byIsbn('9786060339229').offers).toEqual([]);
      expect(svc.unplaced().map((i) => i.isbn)).toEqual(['9786060339229']);
      expect(svc.givenBody()!.items.map((i) => i.isbn13).sort()).toEqual(['9780137081073', '9789735832940']);
      expect(refresh).toHaveBeenCalledTimes(1);
    }));
  });
});
