"""Permanent song metadata and numeric profiles, owned by the catalog repository."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import urllib.request

MAX_SONGS=20000
PAGE_SIZE=200
ORIGIN='https://hirock69.github.io/roblox-music-party-catalog/'

def encoded(value):
    return (json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()

def digest(raw):return hashlib.sha256(raw).hexdigest()

def validate_profile(p,asset):
    assert p['AssetId']==asset and 0<p['Duration']<=300.1
    assert 0<p['Step']<=1 and 0<p['OnsetStep']<=1 and 0<p['ReferenceRms']<=1
    assert abs(len(p['Energy'])*p['Step']-p['Duration'])<=p['Step']+1e-5
    assert len(p['Energy'])<=4000 and all(math.isfinite(v) and 0<=v<=1 for v in p['Energy'])
    assert len(p['Onsets'])<=16000
    previous=0
    for i,v in p['Onsets']:
        assert isinstance(i,int) and previous<i<=math.ceil(p['Duration']/p['OnsetStep'])+1 and 0<v<=1
        previous=i
    assert re.fullmatch('[0-9a-f]{64}',p['SourceSha256'])
    r=p['Rhythm'];assert 0<=r['Bpm']<=300 and 0<=r['Confidence']<=1 and len(r['Beats'])<=3000
    assert all(math.isfinite(v) and 0<=v<p['Duration'] for v in r['Beats'])
    assert all(a<b for a,b in zip(r['Beats'],r['Beats'][1:]))

def metadata(t):
    assert type(t['assetId']) is int and 0<t['assetId']<2**53
    assert isinstance(t['title'],str) and 0<len(t['title'])<=160
    assert isinstance(t['artist'],str) and 0<len(t['artist'])<=120
    assert type(t['manual']) is bool and t['key']==('manual-' if t['manual'] else 'chart-')+str(t['assetId'])
    assert type(t['chartRank']) is int and (t['chartRank']==0 if t['manual'] else 1<=t['chartRank']<=40)
    assert type(t['albumArtAssetId']) is int and 0<=t['albumArtAssetId']<2**53
    assert 0<t['playbackSeconds']<=86400 and 0<=t.get('tailSeconds',0)<=.15
    assert re.fullmatch('[a-f0-9]{64}',t['profileHash']) and t['profile']=='profiles/'+t['profileHash']+'.json'

def read_registry(archive):
    path=archive/'registry.json'
    if not path.exists():return {}
    registry=json.loads(path.read_bytes());assert registry['schema']==1 and len(registry['songs'])<=MAX_SONGS
    songs={}
    for row in registry['songs']:
        metadata(row['track']);asset=row['track']['assetId'];assert asset not in songs
        assert all(isinstance(row[k],str) and 0<len(row[k])<=40 for k in ('firstSeen','lastHot'))
        songs[asset]=row
    return songs

def build_library(root,site,current,policy,timestamp,validate_profile):
    assert 0<len(current)<=80 and len({t['assetId']for t in current})==len(current)
    archive=root/'archive';songs=read_registry(archive)
    for track in current:
        metadata(track);old=songs.get(track['assetId'])
        songs[track['assetId']]={'track':track,'firstSeen':old['firstSeen'] if old else timestamp,'lastHot':timestamp}
    assert 0<len(songs)<=MAX_SONGS
    ordered=[songs[k] for k in sorted(songs)]
    # Source-controlled archive, independent of Actions cache and the HOT window.
    for path in sorted((archive/'profiles').glob('*.json')):
        raw=path.read_bytes();assert len(raw)<=180000 and digest(raw)==path.stem
        profile=json.loads(raw);validate_profile(profile,profile['AssetId'])
        target=site/'profiles'/path.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    for row in ordered:
        track=row['track'];path=site/track['profile']
        raw=path.read_bytes() if path.exists() else (archive/track['profile']).read_bytes()
        assert len(raw)<=180000 and digest(raw)==track['profileHash']
        validate_profile(json.loads(raw),track['assetId'])
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    pages=[]
    for start in range(0,len(ordered),PAGE_SIZE):
        raw=encoded({'schema':1,'songs':ordered[start:start+PAGE_SIZE]});h=digest(raw)
        path='library/'+h+'.json';(site/'library').mkdir(exist_ok=True);(site/path).write_bytes(raw)
        pages.append({'path':path,'hash':h,'count':len(ordered[start:start+PAGE_SIZE])})
    basis={'schema':1,'count':len(ordered),'hot':[t['assetId'] for t in current],'pages':pages,'policy':policy}
    header={**basis,'revision':digest(encoded(basis)),'generatedAt':timestamp}
    (site/'library.json').write_bytes(encoded(header))
    return header

def record_library(root,fetch,validate_profile):
    """Called only after Pages deployment; retain every song and its valid profile."""
    header=json.loads(fetch('library.json',100000))
    assert header['schema']==1 and 0<header['count']<=MAX_SONGS and len(header['pages'])<=100
    songs=[];seen=set();archive=root/'archive'
    previous=read_registry(archive)
    for page in header['pages']:
        assert re.fullmatch('library/[a-f0-9]{64}\\.json',page['path'])
        raw=fetch(page['path'],400000);assert digest(raw)==page['hash']
        body=json.loads(raw);assert body['schema']==1 and len(body['songs'])==page['count']<=PAGE_SIZE
        for row in body['songs']:
            t=row['track'];metadata(t);assert t['assetId'] not in seen;seen.add(t['assetId']);songs.append(row)
            assert all(isinstance(row[k],str) and 0<len(row[k])<=40 for k in ('firstSeen','lastHot'))
            path=archive/t['profile']
            profile=path.read_bytes() if path.exists() else fetch(t['profile'],180000)
            assert digest(profile)==t['profileHash'];validate_profile(json.loads(profile),t['assetId'])
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(profile)
    assert len(songs)==header['count'] and set(previous).issubset(seen),'Permanent library cannot lose songs'
    archive.mkdir(exist_ok=True);(archive/'registry.json').write_bytes(encoded({'schema':1,'songs':songs}))
    return header

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--record',action='store_true',required=True);parser.parse_args()
    def fetch(path,limit):
        with urllib.request.urlopen(ORIGIN+path,timeout=40) as response:raw=response.read(limit+1)
        assert len(raw)<=limit;return raw
    header=record_library(Path(__file__).resolve().parent,fetch,validate_profile)
    print('PASS permanent library recorded',header['count'],header['revision'])
