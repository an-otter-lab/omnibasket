import io, sqlite3
from email.message import Message
from pathlib import Path
from index.pull import book_url, hints, ingest_xml, pull, init, SOURCES

def test_filter_and_hints():
 assert book_url('https://www.libris.ro/p/the-very-hungry-caterpillar')
 assert not book_url('https://www.libris.ro/categorie/copii')
 assert hints('https://x/p/the-very-hungry-caterpillar')[0]=='the very hungry caterpillar'

def test_xml_db_upsert_and_gzip_fixture(tmp_path):
 import gzip
 with gzip.open('tests/fixtures/books.xml.gz','rb') as stream, sqlite3.connect(tmp_path/'x.db') as db:
  init(db); assert ingest_xml(stream,'libris',db)==1
  assert ingest_xml(io.BytesIO(Path('tests/fixtures/books.xml').read_bytes()),'libris',db)==1
  assert db.execute('select count(*) from books').fetchone()[0]==1

def test_conditional_request_and_log(tmp_path):
 class Response(io.BytesIO):
  def __init__(self,b): super().__init__(b); self.headers=Message(); self.headers['ETag']='"tag"'; self.headers['Last-Modified']='Fri, 30 Oct 2026 00:00:00 GMT'
  def __enter__(self): return self
  def __exit__(self,*a): self.close()
 seen=[]
 def openit(req,timeout): seen.append(req); return Response(Path('tests/fixtures/books.xml').read_bytes())
 db=tmp_path/'index.db'; pull('libris',db,openit); pull('libris',db,openit)
 assert seen[1].get_header('If-none-match')=='"tag"'
 with sqlite3.connect(db) as c: assert c.execute('select count(*) from books').fetchone()[0]==1

def test_index_expansion_filter_and_block_log(tmp_path):
 index=b'<sitemapindex><sitemap><loc>https://www.libris.ro/sitemap-carte.xml?nofilename=on&amp;page=1</loc></sitemap></sitemapindex>'
 child=b'<urlset><url><loc>https://www.libris.ro/carte/a-book/123</loc></url><url><loc>https://www.libris.ro/sitemap-categorii.xml</loc></url></urlset>'
 class Response(io.BytesIO):
  def __init__(self,b): super().__init__(b); self.headers=Message()
  def __enter__(self): return self
  def __exit__(self,*a): self.close()
 seen=[]
 def openit(req,timeout):
  seen.append(req.full_url); return Response(index if len(seen)==1 else child)
 result=pull('libris',tmp_path/'i.db',openit)
 assert result['entries_kept']==1 and len(seen)==2
 blocked=pull('emag',tmp_path/'i.db',openit)
 assert blocked['status']=='blocked' and blocked['error']=='HTTP 511 bot wall'
 with sqlite3.connect(tmp_path/'i.db') as db: assert db.execute("select status,error from pulls where shop='emag'").fetchone()==('blocked','HTTP 511 bot wall')

def test_bookzone_404_logged(tmp_path):
 import urllib.error
 def openit(req,timeout): raise urllib.error.HTTPError(req.full_url,404,'Not Found',{},None)
 result=pull('bookzone',tmp_path/'i.db',openit)
 assert result['status']=='error' and result['error']=='HTTP 404'

# --- Elefant (3 Nov): imported books only, stored gzip with no .gz and no Content-Encoding, resumable pulls.
EL='https://www.elefant.ro/'
UUID='ebaa58a4-3ac6-4e9b-b193-63b8901ae1b7'

def test_elefant_book_rule_keeps_binding_suffix_only():
 from index.pull import elefant_slug
 assert book_url(EL+'the-sample-book-paperback_'+UUID)
 assert book_url(EL+'a-board-title-board-book_'+UUID)
 assert book_url(EL+'big-picture-hardcover_'+UUID)
 assert not book_url(EL+'sample-perfume-50-ml_'+UUID)
 assert not book_url(EL+'a-romanian-title_'+UUID)  # no marker: not indexed (imported books only)
 assert not book_url(EL+'a-title-ebook_'+UUID)
 assert not book_url(EL+'list/carti/paperback_'+UUID)
 assert not book_url(EL+'the-sample-book-paperback')
 assert elefant_slug(EL+'the-sample-book-paperback_'+UUID)==('the sample book','paperback')
 assert hints(EL+'the-sample-book-hardback_'+UUID)==('the sample book',None,None)

class _Resp(io.BytesIO):
 def __init__(self,b,headers=None):
  super().__init__(b); self.headers=Message(); self.status=200
  for k,v in (headers or {}).items(): self.headers[k]=v
 def __enter__(self): return self
 def __exit__(self,*a): self.close()

def _elefant_files():
 import gzip
 index=(f'<sitemapindex><sitemap><loc>{EL}sitemap-product-sitemapRO-0</loc></sitemap>'
        f'<sitemap><loc>{EL}sitemap-product-sitemapRO-1</loc></sitemap></sitemapindex>').encode()
 child0=(f'<urlset><url><loc>{EL}one-book-paperback_{UUID}</loc></url>'
         f'<url><loc>{EL}a-scented-candle_{UUID}</loc></url></urlset>').encode()
 child1=f'<urlset><url><loc>{EL}two-book-hardback_{UUID}</loc></url></urlset>'.encode()
 # Stored gzip, served as application/x-gzip with no Content-Encoding and no .gz in the URL.
 z=lambda b: gzip.compress(b,compresslevel=0)
 return index,{EL+'sitemap-product-sitemapRO-0':z(child0),EL+'sitemap-product-sitemapRO-1':z(child1)}

def test_elefant_gzip_by_magic_bytes(tmp_path,monkeypatch):
 monkeypatch.setattr('index.pull.validate_child_url',lambda url,shop:(True,None))
 monkeypatch.setattr('index.pull.DELAY',0)
 index,files=_elefant_files()
 def openit(req,timeout):
  if req.full_url==SOURCES['elefant']: return _Resp(index)
  return _Resp(files[req.full_url],{'Content-Type':'application/x-gzip','Last-Modified':'Sat, 31 Oct 2026 21:04:14 GMT'})
 result=pull('elefant',tmp_path/'i.db',openit)
 assert result['status']=='ok' and result['entries_kept']==2, result
 with sqlite3.connect(tmp_path/'i.db') as db:
  rows=db.execute("select title,isbn from books where shop='elefant' order by title").fetchall()
 assert rows==[('one book',None),('two book',None)]

def test_elefant_pull_stopped_mid_file_resumes(tmp_path,monkeypatch):
 """A file cut short by the deadline is not remembered: the next run reads it again in full,
 and the files already read are asked for conditionally."""
 import urllib.error
 monkeypatch.setattr('index.pull.validate_child_url',lambda url,shop:(True,None))
 monkeypatch.setattr('index.pull.DELAY',0)
 index,files=_elefant_files()
 lm='Sat, 31 Oct 2026 21:04:14 GMT'
 calls=[]; cut=[True]
 def openit(req,timeout):
  calls.append((req.full_url,req.get_header('If-modified-since')))
  if req.full_url==SOURCES['elefant']: return _Resp(index)
  if req.get_header('If-modified-since'): raise urllib.error.HTTPError(req.full_url,304,'Not Modified',{},None)
  body=files[req.full_url]
  if req.full_url.endswith('-1') and cut[0]:
   cut[0]=False
   class Slow(_Resp):
    def read(self,n=-1): raise ValueError('deadline 1200s exceeded')
   return Slow(body,{'Last-Modified':lm})
  return _Resp(body,{'Last-Modified':lm})
 first=pull('elefant',tmp_path/'i.db',openit)
 assert first['status']=='stopped' and first['entries_kept']==1
 calls.clear()
 second=pull('elefant',tmp_path/'i.db',openit)
 assert second['status']=='ok' and second['entries_kept']==1 and second['error'] is None, second
 assert (EL+'sitemap-product-sitemapRO-0',lm) in calls  # conditional: 304
 assert (EL+'sitemap-product-sitemapRO-1',None) in calls  # read again in full
 with sqlite3.connect(tmp_path/'i.db') as db:
  assert db.execute("select count(*) from books where shop='elefant'").fetchone()[0]==2

def test_old_index_gets_new_pull_columns(tmp_path):
 with sqlite3.connect(tmp_path/'old.db') as db:
  db.execute('CREATE TABLE pulls(id INTEGER PRIMARY KEY,shop TEXT NOT NULL,started TEXT NOT NULL,finished TEXT,status TEXT,bytes INTEGER DEFAULT 0,entries_kept INTEGER DEFAULT 0,etag TEXT,error TEXT)')
  init(db)
  assert {'last_modified','stop_reason'} <= {r[1] for r in db.execute('PRAGMA table_info(pulls)')}
