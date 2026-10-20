#!/usr/bin/env python3
"""Fetch pinned public sources, import browser ZIPs, and inventory raw files.

No API token or voter-file subscription is required. If Dataverse blocks API
access, download Original Format ZIP from the pinned dataset page and run:
  python code/collect_data.py --import-ces-zip 2016 /path/to/archive.zip
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile, is_zipfile
import zlib

ROOT=Path(__file__).resolve().parents[1]
CATALOG=ROOT/'docs/source_catalog.json'

def digest(path, algorithm='sha256'):
    h=hashlib.new(algorithm)
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def download(url, path):
    if path.exists():return
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.part')
    try:
        req=Request(url,headers={'User-Agent':'ECON438-P1-academic-data-collection/1.0'})
        with urlopen(req,timeout=60) as src,temp.open('wb') as dst:
            shutil.copyfileobj(src,dst,4*1024*1024)
        if not is_zipfile(temp):raise ValueError('Expected a ZIP/Office file; response was not a valid archive')
        temp.replace(path)
    except Exception:
        if temp.exists():temp.unlink()
        raise

def crc32(path):
    crc=0
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):crc=zlib.crc32(b,crc)
    return crc

def import_zip(year, path, catalog):
    spec=catalog['ces'][str(year)]
    with ZipFile(path) as z:
        if spec['expected_dta'] not in z.namelist():
            raise ValueError(f'Archive does not contain the original {year} Stata file; select the correct year and ORIGINAL format')
    dst=ROOT/'data/CES'/str(year)
    archive=ROOT/'data/CES/archives'/f'ces_{year}_v{spec["version"]}.zip'
    archive.parent.mkdir(parents=True,exist_ok=True)
    if archive.resolve()!=path.resolve():
        if archive.exists():
            if digest(archive)!=digest(path):raise ValueError(f'Existing pinned archive differs: {archive}')
        else:shutil.copyfile(path,archive)
    with ZipFile(archive) as z:
        for info in z.infolist():
            rel=Path(info.filename)
            if rel.is_absolute() or '..' in rel.parts:raise ValueError(f'Unsafe archive path {rel}')
            if info.is_dir():continue
            out=dst/rel
            if out.exists():
                if out.stat().st_size!=info.file_size or crc32(out)!=info.CRC:
                    raise ValueError(f'Existing raw file differs from archive: {out}')
            else:
                out.parent.mkdir(parents=True,exist_ok=True)
                with z.open(info) as src,out.open('wb') as f:shutil.copyfileobj(src,f,4*1024*1024)
    expected=spec['expected_dta']
    if not (dst/expected).exists():raise ValueError(f'Missing original Stata file {expected}; select ORIGINAL Format ZIP')
    print(f'{year}: archive imported; all existing raw files checked against ZIP CRC',flush=True)

def inventory(catalog):
    rows=[]
    now=datetime.now(timezone.utc).isoformat()
    for year,spec in catalog['ces'].items():
        base=ROOT/'data/CES'/year
        if not base.exists():continue
        for p in sorted(base.iterdir()):
            if not p.is_file() or p.name.startswith('ces_core_'):continue
            rows.append({'dataset':'CES','year':year,'release':spec['version'],
                         'source_url':spec['page_url'],'path':p.relative_to(ROOT).as_posix(),
                         'bytes':p.stat().st_size,'sha256':digest(p),
                         'md5_local':digest(p,'md5'),'inventory_at_utc':now,
                         'method':'Original-format dataset ZIP downloaded through Dataverse browser UI'})
        archive=ROOT/'data/CES/archives'/f'ces_{year}_v{spec["version"]}.zip'
        if archive.exists():
            rows.append({'dataset':'CES archive','year':year,'release':spec['version'],
                         'source_url':spec['page_url'],'path':archive.relative_to(ROOT).as_posix(),
                         'bytes':archive.stat().st_size,'sha256':digest(archive),
                         'md5_local':digest(archive,'md5'),'inventory_at_utc':now,
                         'method':'Dataverse ZIP; extracted bytes checked against member CRC'})
    for name,url in catalog['covi']['files'].items():
        p=ROOT/'data/COVI/raw'/name
        if p.exists():rows.append({'dataset':'COVI','year':'1996-2024','release':'website snapshot',
                                  'source_url':url,'path':p.relative_to(ROOT).as_posix(),
                                  'bytes':p.stat().st_size,'sha256':digest(p),
                                  'md5_local':digest(p,'md5'),'inventory_at_utc':now,'method':'Public source download'})
    dest=ROOT/'data/manifest.csv';dest.parent.mkdir(parents=True,exist_ok=True)
    if rows:
        with dest.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(f'Inventory: {len(rows)} raw files/archives; local hashes recorded in {dest}',flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--only',choices=['all','ces','covi','inventory'],default='all')
    p.add_argument('--import-ces-zip',nargs=2,metavar=('YEAR','ZIP'))
    args=p.parse_args();catalog=json.loads(CATALOG.read_text());errors=[]
    if args.import_ces_zip:
        year,path=args.import_ces_zip
        import_zip(int(year),Path(path).expanduser(),catalog)
        return
    if args.only in ['all','ces']:
        for year,spec in catalog['ces'].items():
            target=ROOT/'data/CES'/year/spec['expected_dta']
            expected=spec.get('expected_files',[spec['expected_dta']])
            if target.exists() and all((target.parent/name).exists() for name in expected):
                print(f'CES {year}: existing raw source retained',flush=True)
                continue
            query=urlencode({'persistentId':'doi:'+spec['doi'],'format':'original'})
            url=f'https://dataverse.harvard.edu/api/access/dataset/:persistentId/versions/{spec["version"]}?{query}'
            archive=ROOT/'data/CES/archives'/f'ces_{year}_v{spec["version"]}.zip'
            try:
                download(url,archive);import_zip(int(year),archive,catalog)
            except Exception as e:
                errors.append(f'CES {year}: {e}; browser fallback: {spec["page_url"]}')
    if args.only in ['all','covi']:
        for name,url in catalog['covi']['files'].items():
            try:
                download(url,ROOT/'data/COVI/raw'/name)
                print(f'COVI: {name}',flush=True)
            except Exception as e:errors.append(f'COVI {name}: {e}')
    inventory(catalog)
    if errors:
        print('\n'.join(errors),file=sys.stderr)
        print('For Dataverse API refusals, use the browser Original Format ZIP and --import-ces-zip.',file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__':main()
