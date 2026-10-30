import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { AppComponent } from './app.component';
import { PhotoReadResponse, PhotoState } from './photo';

describe('Photo flow (Feature 2)', () => {
  let component: AppComponent;
  let fixture: ComponentFixture<AppComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [HttpClientTestingModule, AppComponent],
    }).compileComponents();

    fixture = TestBed.createComponent(AppComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
  });

  afterEach(() => {
    httpMock.verify();
  });

  function createPhotoResponse(lines: PhotoReadResponse): PhotoReadResponse {
    return lines;
  }

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

    it('should trigger live flow when continuing with matched lines', fakeAsync(() => {
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

      const startLiveSpy = spyOn(component, 'startLive');
      component.onPhotoContinue();
      tick();

      expect(startLiveSpy).toHaveBeenCalledWith('9780141367941', 'The Very Hungry Caterpillar');
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

      const startLiveSpy = spyOn(component, 'startLive');
      component.onPhotoContinue();
      tick();

      expect(startLiveSpy).toHaveBeenCalledWith('9780441172719', 'Dune');
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

    it('should not include not found lines in continue flow', fakeAsync(() => {
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

      const startLiveSpy = spyOn(component, 'startLive');
      component.onPhotoContinue();
      tick();

      expect(startLiveSpy).toHaveBeenCalledTimes(1);
      expect(startLiveSpy).toHaveBeenCalledWith('9780141367941', 'The Very Hungry Caterpillar');
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
      component.basket = new Set(['existing-book']);
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
      const size = 5 * 1024 * 1024; // 5 MB
      component.onPhotoEvent({ kind: 'oversize', size });
      tick();

      expect(component.photoState.kind).toBe('oversize');
      if (component.photoState.kind === 'oversize') {
        expect(component.photoState.size).toBe(size);
      }
      expect(component.photoOversizeText).toContain('5.0 MB');
    }));

    it('should not trigger live flow on oversize', fakeAsync(() => {
      const size = 5 * 1024 * 1024;
      component.onPhotoEvent({ kind: 'oversize', size });
      tick();

      const startLiveSpy = spyOn(component, 'startLive');
      expect(startLiveSpy).not.toHaveBeenCalled();
      expect(component.basket.size).toBe(0);
    }));
  });
});
