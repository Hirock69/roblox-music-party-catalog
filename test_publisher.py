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

if __name__=='__main__':unittest.main()
