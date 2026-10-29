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
