"""Focused data-producer checks, run before every scheduled deployment."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from publisher import blocked,extract,validate_profile

class PublisherTests(unittest.TestCase):
    def test_human_exclusions(self):
        policy={'excludedArtists':['Human Sound Recorder'],'excludedWords':['Void'],'excludedAssetIds':[42]}
        self.assertEqual(blocked({'assetId':1,'artist':' human sound recorder ','title':'Music'},policy),'artist')
        self.assertEqual(blocked({'assetId':1,'artist':'Artist','title':'vOiD'},policy),'word')
        self.assertEqual(blocked({'assetId':42,'artist':'Artist','title':'Music'},policy),'asset')
        self.assertIsNone(blocked({'assetId':1,'artist':'Artist','title':'Music'},policy))

    def test_long_audio_is_analyzed_only_through_five_minutes(self):
        with tempfile.TemporaryDirectory() as name:
            directory=Path(name);source=directory/'long.flac'
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','sine=frequency=440:sample_rate=22050:duration=301',str(source)],check=True)
            result=extract(source.read_bytes(),123,directory)
            self.assertGreater(result['playbackSeconds'],300)
            self.assertAlmostEqual(result['profile']['Duration'],300,places=2)
            self.assertLessEqual(len(result['profile']['Energy']),3001)
            validate_profile(result['profile'],123)
            with self.assertRaises(AssertionError):validate_profile(result['profile'],124)


    def test_top40_and_exact_artist_title_exclusions(self):
        from unittest.mock import patch
        import json
        import publisher
        policy=json.loads((publisher.ROOT/'selection-policy.json').read_text())
        self.assertEqual(policy['chartLimit'],40)
        self.assertEqual(publisher.blocked({'assetId':72125382966885,'artist':'Renamed Artist','title':'Renamed Song'},policy),'asset')
        for artist in ('Milos Krkoska','Richard Allen Harvey','Einschlafmusik für Babys','Bruton'):
            self.assertEqual(publisher.blocked({'assetId':1,'artist':artist,'title':'Music'},policy),'artist')
        for artist,title in (('Brian Bennett','Twilight Zone'),('Sonoton Vinyl','Threat Of Death'),('NojikoFM','Haunted House')):
            self.assertEqual(publisher.blocked({'assetId':1,'artist':' '+artist.upper()+' ','title':' '+title.upper()+' '},policy),'track')
            self.assertIsNone(publisher.blocked({'assetId':1,'artist':artist,'title':'Other Song'},policy))
            self.assertIsNone(publisher.blocked({'assetId':1,'artist':'Other Artist','title':title},policy))
        songs=[{'assetId':i} for i in range(1,41)]
        with patch.object(publisher,'fetch',return_value=json.dumps({'songs':songs}).encode()) as fetch:
            endpoint,received=publisher.load_chart(policy)
            self.assertEqual(len(received),40);self.assertEqual(received[-1]['assetId'],40)
            self.assertIn('limit=40',endpoint);fetch.assert_called_once_with(endpoint,100000)
        with patch.object(publisher,'fetch',return_value=json.dumps({'songs':songs[:20]}).encode()):
            with self.assertRaises(AssertionError):publisher.load_chart(policy)


    def test_scoped_title_words_and_new_exact_exclusions(self):
        import json
        import publisher
        policy=json.loads((publisher.ROOT/'selection-policy.json').read_text())
        def song(artist,title):return {'assetId':1,'artist':artist,'title':title}
        self.assertEqual(publisher.blocked(song('Jonathan Bourne','Music'),policy),'artist')
        for title in ('Immortals','Epic Trailer'):
            self.assertEqual(publisher.blocked(song('Kosinus',title),policy),'track')
        self.assertIsNone(publisher.blocked(song('Kosinus','Other Music'),policy))
        self.assertEqual(publisher.blocked(song(" MARC DALL'ANESE ",'Powerful ePiC Theme'),policy),'artist-title-word')
        self.assertIsNone(publisher.blocked(song("Marc Dall'Anese",'Quiet Theme'),policy))
        self.assertIsNone(publisher.blocked(song('Other Artist','Epic Theme'),policy))

    def test_transient_throttle_and_registered_metadata(self):
        import json
        import io
        import urllib.error
        from unittest.mock import patch, MagicMock
        import publisher
        response=MagicMock();response.__enter__.return_value.read.return_value=b'healthy'
        error=urllib.error.HTTPError('https://example.test',429,'throttled',{'Retry-After':'1'},None)
        with patch.object(publisher.urllib.request,'urlopen',side_effect=[error,response]) as request,patch.object(publisher.time,'sleep') as sleep:
            self.assertEqual(publisher.fetch('https://example.test'),b'healthy')
            self.assertEqual(request.call_count,2);sleep.assert_called_once_with(1)
        with patch.object(publisher.urllib.request,'urlopen',side_effect=error) as request,patch.object(publisher.time,'sleep'):
            with self.assertRaises(urllib.error.HTTPError):publisher.fetch('https://example.test')
            self.assertEqual(request.call_count,4)
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/'manual-tracks.json').write_text(json.dumps({'schema':1,'tracks':[{'assetId':1,'title':'Verified','artist':'Uploader','albumArtAssetId':0}]}))
            with patch.object(publisher,'ROOT',root),patch.object(publisher,'fetch',side_effect=AssertionError('must not requery metadata')):
                self.assertEqual(publisher.load_manual()[0]['title'],'Verified')

    def test_manual_generation(self):
        import json
        from unittest.mock import patch
        import publisher
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            policy={'chartLimit':40,'excludedArtists':[],'excludedWords':['Void'],'excludedAssetIds':[]}
            (root/'selection-policy.json').write_text(json.dumps(policy))
            (root/'manual-tracks.json').write_text(json.dumps({'schema':1,'tracks':[{'assetId':1},{'assetId':41},{'assetId':42,'title':'Void'}]}))
            chart=[{'assetId':i,'title':'Chart '+str(i),'artist':'Artist','albumArtAssetId':1} for i in range(1,41)]
            def fetch(url,limit=0):
                if 'economy.roblox.com' in url:return json.dumps({'Name':'Manual','AssetTypeId':3,'Creator':{'Name':'Uploader'},'IconImageAssetId':0}).encode()
                return url.encode()
            def extract(raw,asset,workspace):
                return {'playbackSeconds':1,'profile':{'AssetId':asset,'Duration':1,'Step':0.1,'OnsetStep':0.02,'ReferenceRms':0.3,'Energy':[0.5]*10,'Onsets':[[2,0.8]],'SourceSha256':'a'*64,'Rhythm':{'Bpm':120,'Confidence':1,'Beats':[0,0.5]}}}
            with patch.object(publisher,'ROOT',root),patch.object(publisher,'load_chart',return_value=('chart',chart)),patch.object(publisher,'fetch',side_effect=fetch),patch.object(publisher,'extract',side_effect=extract):
                publisher.build()
                m=json.loads((root/'site/manifest.json').read_text())
                self.assertEqual(len(m['tracks']),41)
                manual=[t for t in m['tracks'] if t['manual']]
                self.assertEqual({t['assetId'] for t in manual},{1,41})
                self.assertTrue(all(t['chartRank']==0 and t['albumArtAssetId']==0 for t in manual))
                self.assertEqual(len({t['assetId'] for t in m['tracks']}),41)
                self.assertTrue(all((root/'site'/t['profile']).is_file() for t in m['tracks']))
                (root/'manual-tracks.json').write_text(json.dumps({'schema':1,'tracks':[{'assetId':1},{'assetId':1}]}))
                with self.assertRaises(AssertionError):publisher.load_manual()

    def test_four_requested_song_exclusions(self):
        import json
        import publisher
        policy=json.loads((publisher.ROOT/'selection-policy.json').read_text())
        for artist,title,asset in [('Roger Stephen Dexter', 'Classical Heritage (B)', 1840230230), ('2nd Foundation Music', 'Rogue Pursuit Main orch only', 1835131725), ('Sonoton Vanguard', 'The End Is Now D', 9046267554), ('François Rousselot', 'Army of Darkness', 1843379079)]:
            self.assertEqual(publisher.blocked({'assetId':asset,'artist':'Renamed','title':'Renamed'},policy),'asset')
            self.assertEqual(publisher.blocked({'assetId':1,'artist':artist,'title':title},policy),'track')
            self.assertIsNone(publisher.blocked({'assetId':1,'artist':artist,'title':'Other Song'},policy))
            self.assertIsNone(publisher.blocked({'assetId':1,'artist':'Other Artist','title':title},policy))

if __name__=='__main__':unittest.main()
