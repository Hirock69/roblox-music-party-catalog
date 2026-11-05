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

if __name__=='__main__':unittest.main()
