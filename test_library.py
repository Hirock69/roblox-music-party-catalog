import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from library import build_library,encoded,record_library,validate_profile

class LibraryTests(unittest.TestCase):
    def song(self,site,asset):
        p={'AssetId':asset,'Duration':1,'Step':.1,'OnsetStep':.02,'ReferenceRms':.3,'SourceSha256':'a'*64,'Energy':[.5]*10,'Onsets':[[2,.8]],'Rhythm':{'Bpm':120,'Confidence':1,'Beats':[0,.5]}}
        raw=encoded(p);h=hashlib.sha256(raw).hexdigest();rel='profiles/'+h+'.json';(site/'profiles').mkdir(parents=True,exist_ok=True);(site/rel).write_bytes(raw)
        return {'assetId':asset,'key':'chart-'+str(asset),'title':'Song '+str(asset),'artist':'Artist','manual':False,'chartRank':1,'albumArtAssetId':1,'playbackSeconds':1,'tailSeconds':.1,'profileHash':h,'profile':rel}

    def test_rotation_survives_cache_loss_and_more_than_three_generations(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);first=None
            for n in range(1,7):
                site=root/('site'+str(n));site.mkdir();track=self.song(site,n)
                if first is None:first=track
                h=build_library(root,site,[track],{'excludedAssetIds':[]},'2026-11-0'+str(n),validate_profile)
                self.assertEqual(h['count'],n);self.assertEqual(h['hot'],[n])
                record_library(root,lambda path,limit:(site/path).read_bytes(),validate_profile)
                self.assertTrue((site/first['profile']).is_file())
            registry=json.loads((root/'archive/registry.json').read_bytes())
            self.assertEqual([r['track']['assetId']for r in registry['songs']],[1,2,3,4,5,6])
            self.assertEqual(registry['songs'][0]['firstSeen'],'2026-11-01')
            self.assertFalse((root/'.cache').exists())

    def test_ng_retains_metadata_profile_and_first_seen(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);site=root/'site';site.mkdir();a=self.song(site,1)
            build_library(root,site,[a],{},'day1',validate_profile);record_library(root,lambda p,l:(site/p).read_bytes(),validate_profile)
            other=root/'other';other.mkdir();b=self.song(other,2)
            h=build_library(root,other,[b],{'excludedAssetIds':[1]},'day2',validate_profile)
            page=json.loads((other/h['pages'][0]['path']).read_bytes())
            self.assertEqual(len(page['songs']),2);self.assertEqual(page['songs'][0]['lastHot'],'day1')
            self.assertTrue((other/a['profile']).exists());self.assertEqual(h['policy']['excludedAssetIds'],[1])

    def test_metadata_update_keeps_asset_identity(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);site=root/'site';site.mkdir();a=self.song(site,1)
            build_library(root,site,[a],{},'day1',validate_profile);record_library(root,lambda p,l:(site/p).read_bytes(),validate_profile)
            a.update(key='manual-1',manual=True,chartRank=0,title='New title')
            h=build_library(root,site,[a],{},'day2',validate_profile);self.assertEqual(h['count'],1)
            record_library(root,lambda p,l:(site/p).read_bytes(),validate_profile)
            row=json.loads((root/'archive/registry.json').read_bytes())['songs'][0]
            self.assertEqual(row['firstSeen'],'day1');self.assertEqual(row['lastHot'],'day2')

    def test_corrupt_profile_fails_before_publication(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);site=root/'site';site.mkdir();a=self.song(site,1)
            (site/a['profile']).write_bytes(b'{}\n')
            with self.assertRaises(AssertionError):build_library(root,site,[a],{},'day1',validate_profile)

    def test_archive_cannot_lose_old_song(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);site=root/'site';site.mkdir();a=self.song(site,1)
            build_library(root,site,[a],{},'day1',validate_profile);record_library(root,lambda p,l:(site/p).read_bytes(),validate_profile)
            other=root/'other';other.mkdir();b=self.song(other,2)
            # Simulate an incomplete server response built without the durable source.
            empty=root/'empty';empty.mkdir();build_library(empty,other,[b],{},'day2',validate_profile)
            with self.assertRaises(AssertionError):record_library(root,lambda p,l:(other/p).read_bytes(),validate_profile)

    def test_pages_are_bounded_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);site=root/'site';site.mkdir();tracks=[self.song(site,i)for i in range(1,202)]
            archive=root/'archive';archive.mkdir();(archive/'registry.json').write_bytes(encoded({'schema':1,'songs':[{'track':t,'firstSeen':'day1','lastHot':'day1'}for t in tracks]}))
            h=build_library(root,site,[tracks[0]],{},'day1',validate_profile)
            self.assertEqual([p['count']for p in h['pages']],[200,1])
            h['pages'][0]['path']='../source.py';(site/'library.json').write_bytes(encoded(h))
            with self.assertRaises(AssertionError):record_library(root,lambda p,l:(site/p).read_bytes(),validate_profile)

if __name__=='__main__':unittest.main()
