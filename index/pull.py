"""Polite, bounded sitemap ingestion for Omnibasket."""
from __future__ import annotations
import argparse
import gzip
import ipaddress
import re
import socket
import sqlite3
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
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
# Per-response cap for a single HTTP response body.
MAX_BYTES=50_000_000
# Per-shop aggregate budget for the entire pull (all sitemaps combined).
AGGREGATE_BUDGET=250_000_000
# Wall-clock deadline per shop pull (seconds).
DEADLINE=300
TIMEOUT=30; DELAY=.2; MAX_SITEMAPS=30; MAX_DEPTH=2
# Allowed hosts per shop (domain and www.<domain>).
ALLOWED_HOSTS={
 'libris': ('libris.ro', 'www.libris.ro'),
 'bookzone': ('bookzone.ro', 'www.bookzone.ro'),
 'books-express': ('books-express.ro', 'www.books-express.ro'),
 'emag': ('emag.ro', 'www.emag.ro'),
}

def validate_child_url(url, shop):
 """Validate a child sitemap URL. Return (ok, reason)."""
 try:
  parsed = urlparse(url)
 except Exception as e:
  return False, f'parse error: {e}'
 if parsed.scheme not in ('http', 'https'):
  return False, f'invalid scheme {parsed.scheme}'
 host = parsed.netloc.lower().split(':')[0]
 if not host:
  return False, 'missing host'
 allowed = ALLOWED_HOSTS.get(shop)
 if allowed and host not in allowed:
  return False, f'host {host} not in allowed {allowed}'
 # Resolve host and check for private/loopback/link-local ranges
 try:
  addrs = socket.getaddrinfo(host, None)
  for addr in addrs:
   ip = ipaddress.ip_address(addr[4][0])
   if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved:
    return False, f'private/reserved IP {ip}'
   if str(ip) == '169.254.169.254':
    return False, 'metadata endpoint 169.254.169.254'
 except socket.gaierror:
  return False, f'cannot resolve {host}'
 return True, None

ISBN_RE=re.compile(r'(?<!\d)(?:9[89])?\d{9}[\dX](?!\d)',re.I)
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
 db.executescript('''
  CREATE TABLE IF NOT EXISTS books(shop TEXT NOT NULL,url TEXT NOT NULL,title TEXT,author_hint TEXT,isbn TEXT,last_seen TEXT NOT NULL,PRIMARY KEY(shop,url));
  CREATE TABLE IF NOT EXISTS pulls(id INTEGER PRIMARY KEY,shop TEXT NOT NULL,started TEXT NOT NULL,finished TEXT,status TEXT,bytes INTEGER DEFAULT 0,entries_kept INTEGER DEFAULT 0,etag TEXT,error TEXT,last_modified TEXT,stop_reason TEXT);
  CREATE TABLE IF NOT EXISTS sitemap_http(url TEXT PRIMARY KEY,etag TEXT,last_modified TEXT,last_status INTEGER,last_fetched TEXT);
 ''')
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

def fetch_one(url,shop,db,opener,headers=None,aggregate_bytes=None,deadline=None):
 req=urllib.request.Request(url,headers={'User-Agent':UA,'Accept-Encoding':'gzip',**(headers or {})})
 # Check sitemap_http for conditional GET
 row = db.execute('SELECT etag,last_modified FROM sitemap_http WHERE url=?', (url,)).fetchone()
 if row:
  if row[0]: req.add_header('If-None-Match', row[0])
  if row[1]: req.add_header('If-Modified-Since', row[1])
 with opener(req,timeout=TIMEOUT) as resp:
  status_code = resp.status if hasattr(resp, 'status') else 200
  resp_etag = resp.headers.get('ETag')
  resp_modified = resp.headers.get('Last-Modified')
  # Update sitemap_http cache
  db.execute('INSERT OR REPLACE INTO sitemap_http(url,etag,last_modified,last_status,last_fetched) VALUES(?,?,?,?,?)',
   (url, resp_etag, resp_modified, status_code, time.strftime('%Y-%m-%dT%H:%M:%S%z')))
  db.commit()
  if status_code == 304:
   return 0, 0, resp_etag, resp_modified, [], True  # not_modified=True
  raw=resp
  if url.endswith('.gz') or resp.headers.get('Content-Encoding')=='gzip': raw=gzip.GzipFile(fileobj=resp)
  class Bounded:
   total=0
   def read(self,n=-1):
    chunk_size = min(n if n>=0 else 65536, 65536)
    b=raw.read(chunk_size); self.total+=len(b)
    if aggregate_bytes is not None:
     aggregate_bytes[0] += len(b)
     if aggregate_bytes[0] > AGGREGATE_BUDGET:
      raise ValueError(f'aggregate budget {AGGREGATE_BUDGET} exceeded')
    if self.total>MAX_BYTES: raise ValueError('resource exceeds byte cap')
    if deadline is not None and time.monotonic() > deadline[0]:
     raise ValueError(f'deadline {DEADLINE}s exceeded')
    return b
  reader=Bounded(); children=[]; kept=ingest_xml(reader,shop,db,children)
  return kept, reader.total, resp_etag, resp_modified, children, False  # not_modified=False
def pull(shop,dbpath=DB,opener=None):
 opener=opener or urllib.request.urlopen; dbpath.parent.mkdir(parents=True,exist_ok=True)
 with sqlite3.connect(dbpath) as db:
  init(db); started=time.strftime('%Y-%m-%dT%H:%M:%S%z')
  pid=db.execute('INSERT INTO pulls(shop,started,status) VALUES(?,?,?)',(shop,started,'running')).lastrowid; db.commit()
  if shop in LOCAL_SHOPS:
   start=time.monotonic(); kept=ingest_amazon(db)
   db.execute('UPDATE pulls SET finished=?,status=?,entries_kept=? WHERE id=?',(time.strftime('%Y-%m-%dT%H:%M:%S%z'),'ok',kept,pid)); db.commit()
   return {'shop':shop,'status':'ok','entries_kept':kept,'seconds':round(time.monotonic()-start,2),'error':None,'stop_reason':None}
  if not SOURCES[shop]:
   error=BLOCKED.get(shop,'no source')
   db.execute('UPDATE pulls SET finished=?,status=?,error=? WHERE id=?',(time.strftime('%Y-%m-%dT%H:%M:%S%z'),'blocked',error,pid)); db.commit()
   return {'shop':shop,'status':'blocked','entries_kept':0,'seconds':0,'error':error,'stop_reason':None}
  # Set up aggregate budget and deadline tracking
  aggregate_bytes = [0]
  deadline = [time.monotonic() + DEADLINE]
  req=urllib.request.Request(SOURCES[shop],headers={'User-Agent':UA,'Accept-Encoding':'gzip'})
  old=db.execute("SELECT etag,last_modified FROM pulls WHERE shop=? AND id<>? AND status IN ('ok','not-modified') ORDER BY id DESC LIMIT 1",(shop,pid)).fetchone()
  if old:
   if old[0]: req.add_header('If-None-Match',old[0])
   if old[1]: req.add_header('If-Modified-Since',old[1])
  start=time.monotonic(); total=kept=0; etag=modified=None; status='error'; error=None; stop_reason=None
  try:
   with opener(req,timeout=TIMEOUT) as resp:
    status_code = resp.status if hasattr(resp, 'status') else 200
    etag=resp.headers.get('ETag'); modified=resp.headers.get('Last-Modified'); raw=resp
    # Update sitemap_http cache for root URL
    db.execute('INSERT OR REPLACE INTO sitemap_http(url,etag,last_modified,last_status,last_fetched) VALUES(?,?,?,?,?)',
     (SOURCES[shop], etag, modified, status_code, time.strftime('%Y-%m-%dT%H:%M:%S%z')))
    db.commit()
    if SOURCES[shop].endswith('.gz') or resp.headers.get('Content-Encoding')=='gzip': raw=gzip.GzipFile(fileobj=resp)
    class Bounded:
     def read(self,n=-1):
      nonlocal total
      chunk_size = min(n if n>=0 else 65536, 65536)
      b=raw.read(chunk_size); total+=len(b)
      aggregate_bytes[0] += len(b)
      if aggregate_bytes[0] > AGGREGATE_BUDGET:
       raise ValueError(f'aggregate budget {AGGREGATE_BUDGET} exceeded')
      if total>MAX_BYTES: raise ValueError('resource exceeds byte cap')
      if time.monotonic() > deadline[0]:
       raise ValueError(f'deadline {DEADLINE}s exceeded')
      return b
    children=[]; kept=ingest_xml(Bounded(),shop,db,children); status='ok' if status_code != 304 else 'not-modified'
    seen={SOURCES[shop]}; queue=[(u,1) for u in children[:MAX_SITEMAPS]]
    while queue:
     child,depth=queue.pop(0)
     if child in seen or depth>MAX_DEPTH or len(seen)>=MAX_SITEMAPS+1: continue
     # Validate child URL before fetching
     ok, reason = validate_child_url(child, shop)
     if not ok:
      if error: error += f'; {child}: {reason}'
      else: error = f'{child}: {reason}'
      continue
     seen.add(child); time.sleep(DELAY)
     try:
      k,n,_,_,nested,not_modified=fetch_one(child,shop,db,opener,aggregate_bytes=aggregate_bytes,deadline=deadline); kept+=k; total+=n
      if depth<MAX_DEPTH: queue.extend((u,depth+1) for u in nested[:MAX_SITEMAPS])
     except urllib.error.HTTPError as e:
      error=f'{child}: HTTP {e.code}'
     except ValueError as e:
      # Budget or deadline exceeded
      stop_reason = str(e)
      status = 'stopped'
      break
     except Exception as e: error=f'{child}: {type(e).__name__}: {e}'[:300]
  except urllib.error.HTTPError as e:
   if e.code==304: status='not-modified'
   else: error=f'HTTP {e.code}'
  except ValueError as e:
   stop_reason = str(e)
   status = 'stopped'
  except Exception as e: error=f'{type(e).__name__}: {e}'[:300]
  db.execute('UPDATE pulls SET finished=?,status=?,bytes=?,entries_kept=?,etag=?,error=?,last_modified=?,stop_reason=? WHERE id=?',(time.strftime('%Y-%m-%dT%H:%M:%S%z'),status,total,kept,etag,error,modified,stop_reason,pid)); db.commit()
  return {'shop':shop,'status':status,'entries_kept':kept,'seconds':round(time.monotonic()-start,2),'error':error,'stop_reason':stop_reason}
def main():
 p=argparse.ArgumentParser(); p.add_argument('--shop',choices=list(SOURCES)+list(LOCAL_SHOPS)); a=p.parse_args()
 for i,s in enumerate([a.shop] if a.shop else list(SOURCES)+list(LOCAL_SHOPS)):
  if i: time.sleep(DELAY)
  print(pull(s))
if __name__=='__main__': main()
