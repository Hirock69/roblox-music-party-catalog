"""Build an atomic, data-only Pages generation. Run from this directory."""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from audio_features import analyze, rhythm

ROOT=Path(__file__).resolve().parent
ORIGIN='https://hirock69.github.io/roblox-music-party-catalog/'

def fetch(url,limit=30_000_000):
    request=urllib.request.Request(url,headers={'Accept-Encoding':'identity','User-Agent':'MusicPartyCatalog/1'})
    with urllib.request.urlopen(request,timeout=30) as response:raw=response.read(limit+1)
    if len(raw)>limit:raise ValueError('Response too large')
    if raw.startswith(b'\x1f\x8b'):
        raw=gzip.decompress(raw)
        if len(raw)>limit:raise ValueError('Expanded response too large')
    return raw

def encoded(value):return (json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(value):return hashlib.sha256(value).hexdigest()
def blocked(song,policy):
    if song['assetId'] in policy['excludedAssetIds']:return 'asset'
    if song['artist'].strip().lower() in [v.strip().lower() for v in policy['excludedArtists']]:return 'artist'
    artist=song['artist'].strip().lower();title=song['title'].strip().lower()
    if any(artist==pair['artist'].strip().lower() and title==pair['title'].strip().lower() for pair in policy.get('excludedTracks',[])):return 'track'
    if any(artist==rule['artist'].strip().lower() and rule['word'].strip().lower() in title for rule in policy.get('excludedTrackWords',[])):return 'artist-title-word'
    text=(song['title']+' '+song['artist']).lower()
    return 'word' if any(v.strip().lower() in text for v in policy['excludedWords']) else None

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

def extract(raw,asset,workspace):
    source=workspace/'source.audio';wav=workspace/'decoded.wav';source.write_bytes(raw)
    result=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(source)],check=True,capture_output=True,text=True)
    duration=float(result.stdout.strip());assert math.isfinite(duration) and 0<duration<=86400
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-t','300','-ac','1','-c:a','pcm_s16le',str(wav)],check=True)
    f=analyze(wav);r=rhythm(wav)
    profile={'AssetId':asset,'Step':f['step'],'OnsetStep':f['onsetStep'],'Duration':f['duration'],
        'ReferenceRms':f['referenceRms'],'SourceSha256':digest(raw),'Energy':f['energy'],
        'Onsets':[[i+1,v] for i,v in enumerate(f['onset']) if v>0],
        'Rhythm':{'Bpm':r['bpm'],'Confidence':r['confidence'],'Beats':r['beats']}}
    validate_profile(profile,asset)
    # Decoder padding varies slightly. Keep a small bounded tail without looping.
    return dict(profile=profile,playbackSeconds=max(duration,f['duration']),tailSeconds=0.1)

def load_chart(policy):
    limit=policy['chartLimit'];assert type(limit) is int and 1<=limit<=40
    assert all(isinstance(v,str) and v.strip() for key in ('excludedArtists','excludedWords') for v in policy[key])
    assert all(type(pair) is dict and all(isinstance(pair.get(k),str) and pair[k].strip() for k in ('artist','title')) for pair in policy.get('excludedTracks',[]))
    assert all(type(rule) is dict and all(isinstance(rule.get(k),str) and rule[k].strip() for k in ('artist','word')) for rule in policy.get('excludedTrackWords',[]))
    endpoint='https://apis.roblox.com/music-discovery/v1/top-songs?pageToken=0&limit='+str(limit)
    response=json.loads(fetch(endpoint,100000));songs=response['songs'];assert len(songs)==limit
    assert len({s['assetId'] for s in songs})==limit
    return endpoint,songs

def load_manual():
    data=json.loads((ROOT/'manual-tracks.json').read_text())
    assert data['schema']==1 and isinstance(data['tracks'],list) and len(data['tracks'])<=40
    seen=set();songs=[]
    for entry in data['tracks']:
        asset=entry['assetId'];assert type(asset) is int and 0<asset<2**53 and asset not in seen
        seen.add(asset)
        meta=json.loads(fetch('https://economy.roblox.com/v2/assets/'+str(asset)+'/details',100000))
        assert meta['AssetTypeId']==3,'Manual asset must be audio'
        song={'assetId':asset,'title':entry.get('title',meta['Name']),
              'artist':entry.get('artist',meta['Creator']['Name']),
              'albumArtAssetId':entry.get('albumArtAssetId',meta.get('IconImageAssetId',0)),
              'manual':True,'chartRank':0}
        assert isinstance(song['title'],str) and song['title'].strip() and isinstance(song['artist'],str) and song['artist'].strip()
        assert type(song['albumArtAssetId']) is int and 0<=song['albumArtAssetId']<2**53
        songs.append(song)
    return songs

def merge_songs(chart,manual):
    # A Human registration replaces its chart copy; one asset gets one deck slot.
    ids={s['assetId'] for s in manual}
    return [dict(s,chartRank=i) for i,s in enumerate(chart,1) if s['assetId'] not in ids]+manual

def build(seed=None):
    policy=json.loads((ROOT/'selection-policy.json').read_text())
    endpoint,chart=load_chart(policy)
    songs=merge_songs(chart,load_manual())
    cache=ROOT/'.cache';cache.mkdir(exist_ok=True);site=ROOT/'site'
    if site.exists():shutil.rmtree(site)
    (site/'profiles').mkdir(parents=True)
    rows=[];report=[];timestamp=datetime.now(timezone.utc).isoformat()
    for song in songs:
        rank=song['chartRank']
        reason=blocked(song,policy)
        if reason:report.append({'rank':rank,'assetId':song['assetId'],'excluded':reason});continue
        try:
            asset=song['assetId'];assert type(asset) is int and 0<asset<2**53
            assert isinstance(song['title'],str) and 0<len(song['title'])<=160 and isinstance(song['artist'],str) and len(song['artist'])<=120
            raw=fetch('https://assetdelivery.roblox.com/v1/asset/?id='+str(asset));source_hash=digest(raw)
            path=cache/(str(asset)+'-'+source_hash+'.json')
            if path.exists():data=json.loads(path.read_text());validate_profile(data['profile'],asset)
            else:
                with tempfile.TemporaryDirectory() as work:data=extract(raw,asset,Path(work))
                path.write_bytes(encoded(data))
            profile=data['profile'];validate_profile(profile,asset);payload=encoded(profile);profile_hash=digest(payload)
            assert len(payload)<=180000
            rel='profiles/'+profile_hash+'.json';(site/rel).write_bytes(payload)
            row={'key':('manual-' if song.get('manual') else 'chart-')+str(asset),'assetId':asset,'title':song['title'],'artist':song['artist'],
                'manual':song.get('manual',False),'albumArtAssetId':song['albumArtAssetId'],'chartRank':rank,'playbackSeconds':data['playbackSeconds'],
                'tailSeconds':data.get('tailSeconds',0),'profile':rel,'profileHash':profile_hash}
            rows.append(row);report.append({'rank':rank,'assetId':asset,'analysis':'ready','seconds':data['playbackSeconds']})
            print('READY',rank,song['title'],flush=True)
        except Exception as exc:
            report.append({'rank':rank,'assetId':song.get('assetId'),'excluded':'unavailable-or-analysis-failed','error':str(exc)[:240]})
            print('EXCLUDED',rank,str(exc)[:160],flush=True)
    assert len(rows)>=max(1,min(3,sum(not blocked(s,policy) for s in songs))),'Insufficient valid analyzed songs; previous generation retained'
    basis={'schema':1,'policy':policy,'tracks':rows};revision=digest(encoded(basis))
    manifest={**basis,'revision':revision,'generatedAt':timestamp,'source':endpoint}
    # Retain two prior generations so a request straddling deployment stays valid.
    history_path=cache/'history.json';history=json.loads(history_path.read_text()) if history_path.exists() else []
    history=[h for h in history if h['revision']!=revision][:2]
    for old in history:
        for row in old['tracks']:
            filename=row['profile'];stored=cache/('profile-'+row['profileHash']+'.json')
            if stored.exists() and not (site/filename).exists():(site/filename).write_bytes(stored.read_bytes())
    for row in rows:(cache/('profile-'+row['profileHash']+'.json')).write_bytes((site/row['profile']).read_bytes())
    history_path.write_bytes(encoded([manifest]+history))
    (site/'manifest.json').write_bytes(encoded(manifest));(site/'health.json').write_bytes(encoded({'generatedAt':timestamp,'revision':revision,'eligible':len(rows),'report':report}))
    (site/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Music Party catalog</title><h1>Music Party catalog</h1><p>Numeric music analysis only; no audio or game source.</p><a href="manifest.json">Catalog</a> · <a href="health.json">Update health</a>\n')
    print('PASS complete generation',revision,len(rows),'songs',flush=True)

if __name__=='__main__':build()
