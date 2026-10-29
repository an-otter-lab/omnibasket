"""Polite, bounded sitemap ingestion for Omnibasket."""
from __future__ import annotations
import argparse, gzip, re, sqlite3, time, urllib.error, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse
ROOT=Path(__file__).resolve().parent.parent
DB=ROOT/'data/index/books.sqlite3'
SOURCES={'libris':'https://www.libris.ro/sitemap-new-url-index.xml?nofilename=on','bookzone':'https://bookzone.ro/sitemaps-g/SitemapProduse.aspx','emag':None,'books-express':'https://www.books-express.ro/sitemap_index.xml.gz'}
# Amazon.de is never pulled: its slice is the captured books already in the repo.
LOCAL_SHOPS=('amazon_de',)
# eMAG: robots.txt and every /sitemap* path answered HTTP 511 on 2026-10-30.
BLOCKED={'emag':'HTTP 511 bot wall'}
UA='Omnibasket/1.0 (+https://omnibasket.anottersolution.com/contact)'
MAX_BYTES=50_000_000; TIMEOUT=30; DELAY=.2; MAX_SITEMAPS=30; MAX_DEPTH=2
ISBN_RE=re.compile(r'(?<!\d)(?:97[89])?\d{9}[\dX](?!\d)',re.I)
def book_url(url):
 p=urlparse(url); h=p.netloc.lower(); x=unquote(p.path).lower()
 if p.scheme not in ('http','https') or not h or any(k in x for k in ('/category','/categorie','/images/','/img/')): return False
 if h.endswith('emag.ro'): return any(k in x for k in ('/book/','/carte/','/carti/'))
 if h.endswith('libris.ro'): return any(k in x for k in ('/p/','/carte/')) or bool(ISBN_RE.search(x))
 if h.endswith('bookzone.ro'): return '/produs/' in x or '/product/' in x
# Books-Express product URLs are /<slug>/p/<code>,<isbn13> (e.g.
# https://www.books-express.ro/how-to-deal-with-adversity/p/wppm,9780230771666).
 if 'books-express.ro' in h: return '/p/' in x and bool(ISBN_RE.search(x))
 return False
def hints(url,entry=''):
 text=' '.join((unquote(url),entry)); m=ISBN_RE.search(text)
 segments=[s for s in unquote(urlparse(url).path).split('/') if s and not s.isdigit() and s not in ('carte','p','-')]
 slug=max(segments,key=len).rsplit('.',1)[0] if segments else ''
 slug=re.sub(r'[-_]+',' ',slug); slug=re.sub(r'\b(?:978\d{10}|\d{9}[\dx])\b',' ',slug,flags=re.I); slug=re.sub(r'\b\d{1,4}\b',' ',slug)
 title=' '.join(slug.split()).strip(' -') or None; author=None
 a=re.search(r'(?:author|autor|by)[:=\s]+([^|,;]+)',entry,re.I)
 if a: author=a.group(1).strip()
 return title,author,m.group(0) if m else None
def init(db):
 db.executescript('CREATE TABLE IF NOT EXISTS books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url)); CREATE TABLE IF NOT EXISTS pulls(id INTEGER PRIMARY KEY,shop TEXT NOT NULL,started TEXT NOT NULL,finished TEXT,status TEXT,bytes INTEGER DEFAULT 0,entries_kept INTEGER DEFAULT 0,etag TEXT,error TEXT,last_modified TEXT);')
 try:
  from index.search import ensure_books_search
 except ImportError:
  from search import ensure_books_search
 ensure_books_search(db)
def ingest_amazon(db,basket=None):
 import yaml
 path=basket or ROOT/'data/baskets/ro-v1.yaml'
 data=yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
 kept=0
 for book in data.get('books',[]):
  for offer in book.get('offers',[]):
   if offer.get('store_id')!='amazon_de': continue
   url=offer.get('listing_url') or f"capture:{book.get('id')}"
   title=book.get('title'); isbn=book.get('isbn13')
   db.execute('INSERT INTO books VALUES(?,?,?,?,?,?) ON CONFLICT(shop,url) DO UPDATE SET title=excluded.title,author_hint=excluded.author_hint,isbn=COALESCE(excluded.isbn,books.isbn),last_seen=excluded.last_seen',('amazon_de',url,title,None,isbn,time.strftime('%Y-%m-%d')))
   kept+=1
 return kept
def ingest_xml(stream,shop,db,children=None):
 kept=0
 for _,el in ET.iterparse(stream,events=('end',)):
  if el.tag.rsplit('}',1)[-1].lower() in ('url','sitemap'):
   loc=el.find('{*}loc')
   if loc is not None and loc.text:
    url=loc.text.strip()
    if el.tag.rsplit('}',1)[-1].lower()=='sitemap' and children is not None:
     children.append(url)
    elif book_url(url):
     title,author,isbn=hints(url,ET.tostring(el,encoding='unicode'))
     db.execute('INSERT INTO books VALUES(?,?,?,?,?,?) ON CONFLICT(shop,url) DO UPDATE SET title=excluded.title,author_hint=excluded.author_hint,isbn=COALESCE(excluded.isbn,books.isbn),last_seen=excluded.last_seen',(shop,url,title,author,isbn,time.strftime('%Y-%m-%d'))); kept+=1
   el.clear()
 return kept

def fetch_one(url,shop,db,opener,headers=None):
 req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Encoding':'gzip',**(headers or {})})
 with opener(req,timeout=TIMEOUT) as resp:
  raw=resp
  if url.endswith('.gz') or resp.headers.get('Content-Encoding')=='gzip': raw=gzip.GzipFile(fileobj=resp)
  class Bounded:
   total=0
   def read(self,n=-1):
    b=raw.read(min(n if n>=0 else 65536,65536)); self.total+=len(b)
    if self.total>MAX_BYTES: raise ValueError('resource exceeds byte cap')
    return b
  reader=Bounded(); children=[]; kept=ingest_xml(reader,shop,db,children)
  return kept, reader.total, resp.headers.get('ETag'), resp.headers.get('Last-Modified'), children
def pull(shop,dbpath=DB,opener=None):
 opener=opener or urllib.request.urlopen; dbpath.parent.mkdir(parents=True,exist_ok=True)
 with sqlite3.connect(dbpath) as db:
  init(db); started=time.strftime('%Y-%m-%dT%H:%M:%S%z'); pid=db.execute('INSERT INTO pulls(shop,started,status) VALUES(?,?,?)',(shop,started,'running')).lastrowid; db.commit()
  if shop in LOCAL_SHOPS:
   start=time.monotonic(); kept=ingest_amazon(db)
   db.execute('UPDATE pulls SET finished=?,status=?,entries_kept=? WHERE id=?',(time.strftime('%Y-%m-%dT%H:%M:%S%z'),'ok',kept,pid)); db.commit()
   return {'shop':shop,'status':'ok','entries_kept':kept,'seconds':round(time.monotonic()-start,2),'error':None}
  if not SOURCES[shop]:
   error=BLOCKED.get(shop,'no source')
   db.execute('UPDATE pulls SET finished=?,status=?,error=? WHERE id=?',(time.strftime('%Y-%m-%dT%H:%M:%S%z'),'blocked',error,pid)); db.commit()
   return {'shop':shop,'status':'blocked','entries_kept':0,'seconds':0,'error':error}
  req=urllib.request.Request(SOURCES[shop],headers={'User-Agent':UA,'Accept-Encoding':'gzip'})
  old=db.execute("SELECT etag,last_modified FROM pulls WHERE shop=? AND id<>? AND status IN ('ok','not-modified') ORDER BY id DESC LIMIT 1",(shop,pid)).fetchone()
  if old:
   if old[0]: req.add_header('If-None-Match',old[0])
   if old[1]: req.add_header('If-Modified-Since',old[1])
  start=time.monotonic(); total=kept=0; etag=modified=None; status='error'; error=None
  try:
   with opener(req,timeout=TIMEOUT) as resp:
    etag=resp.headers.get('ETag'); modified=resp.headers.get('Last-Modified'); raw=resp
    if SOURCES[shop].endswith('.gz') or resp.headers.get('Content-Encoding')=='gzip': raw=gzip.GzipFile(fileobj=resp)
    class Bounded:
     def read(self,n=-1):
      nonlocal total
      b=raw.read(min(n if n>=0 else 65536,65536)); total+=len(b)
      if total>MAX_BYTES: raise ValueError('resource exceeds byte cap')
      return b
    children=[]; kept=ingest_xml(Bounded(),shop,db,children); status='ok'
    seen={SOURCES[shop]}; queue=[(u,1) for u in children[:MAX_SITEMAPS]]
    while queue:
     child,depth=queue.pop(0)
     if child in seen or depth>MAX_DEPTH or len(seen)>=MAX_SITEMAPS+1: continue
     seen.add(child); time.sleep(DELAY)
     try:
      k,n,_,_,nested=fetch_one(child,shop,db,opener); kept+=k; total+=n
      if depth<MAX_DEPTH: queue.extend((u,depth+1) for u in nested[:MAX_SITEMAPS])
     except urllib.error.HTTPError as e:
      error=f'{child}: HTTP {e.code}'
     except Exception as e: error=f'{child}: {type(e).__name__}: {e}'[:300]
  except urllib.error.HTTPError as e:
   if e.code==304: status='not-modified'
   else: error=f'HTTP {e.code}'
  except Exception as e: error=f'{type(e).__name__}: {e}'[:300]
  db.execute('UPDATE pulls SET finished=?,status=?,bytes=?,entries_kept=?,etag=?,error=?,last_modified=? WHERE id=?',(time.strftime('%Y-%m-%dT%H:%M:%S%z'),status,total,kept,etag,error,modified,pid)); db.commit()
  return {'shop':shop,'status':status,'entries_kept':kept,'seconds':round(time.monotonic()-start,2),'error':error}
def main():
 p=argparse.ArgumentParser(); p.add_argument('--shop',choices=list(SOURCES)); p.add_argument('--rebuild-fts',action='store_true'); a=p.parse_args()
 if a.rebuild_fts:
  try:
   from index.search import refresh_fts
  except ImportError:
   from search import refresh_fts
  refresh_fts(DB); print({'rebuild_fts':True,'db':str(DB)})
  if not a.shop: return
 for i,s in enumerate([a.shop] if a.shop else list(SOURCES)+list(LOCAL_SHOPS)):
  if i: time.sleep(DELAY)
  print(pull(s))
if __name__=='__main__': main()
