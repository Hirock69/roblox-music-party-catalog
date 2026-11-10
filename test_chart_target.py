"""Exercise the real publisher, archive, cache and bounded ranked search."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import publisher

class ChartTargetTests(unittest.TestCase):
    def setup_root(self,root,target=20,manual_count=2):
        policy={'chartLimit':100,'chartTarget':target,'excludedArtists':[],
                'excludedWords':['Void'],'excludedAssetIds':list(range(1,26))}
        (root/'selection-policy.json').write_text(json.dumps(policy))
        manual=[{'assetId':asset,'title':'Manual','artist':'Artist','albumArtAssetId':0}
                for asset in [26]+list(range(200,200+manual_count-1))]
        manual.append({'assetId':300,'title':'Void','artist':'Artist','albumArtAssetId':0})
        (root/'manual-tracks.json').write_text(json.dumps({'schema':1,'tracks':manual}))
        return policy

    def run_build(self,root):
        deliveries=[]
        def fetch(url,limit=0):
            if 'top-songs' in url:
                return json.dumps({'songs':[{'assetId':i,'title':'Chart '+str(i),'artist':'Artist','albumArtAssetId':1}for i in range(1,101)]}).encode()
            asset=int(url.rsplit('=',1)[1]);deliveries.append(asset)
            if asset==27:raise OSError('audio unavailable')
            return str(asset).encode()
        def extract(raw,asset,workspace):
            return {'playbackSeconds':1,'profile':{'AssetId':asset if asset!=28 else -1,
                    'Duration':1,'Step':.1,'OnsetStep':.02,'ReferenceRms':.3,'SourceSha256':'a'*64,
                    'Energy':[.5]*10,'Onsets':[[2,.8]],'Rhythm':{'Bpm':120,'Confidence':1,'Beats':[0,.5]}}}
        with patch.object(publisher,'ROOT',root),patch.object(publisher,'fetch',side_effect=fetch),patch.object(publisher,'extract',side_effect=extract),contextlib.redirect_stdout(io.StringIO()):
            publisher.build()
        return json.loads((root/'site/manifest.json').read_bytes()),json.loads((root/'site/health.json').read_bytes()),deliveries

    def test_twenty_successful_chart_songs_backfill_ng_manual_overlap_and_failures(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);self.setup_root(root)
            manifest,health,deliveries=self.run_build(root)
            chart=[t for t in manifest['tracks']if not t['manual']]
            manual=[t for t in manifest['tracks']if t['manual']]
            self.assertEqual([t['chartRank']for t in chart],list(range(29,49)))
            self.assertEqual({t['assetId']for t in manual},{26,200})
            self.assertEqual(len({t['assetId']for t in manifest['tracks']}),22)
            self.assertEqual((health['chartTarget'],health['chartEligible'],health['manualEligible']),(20,20,2))
            self.assertNotIn(49,deliveries);self.assertNotIn(300,deliveries)
            self.assertTrue(all(i not in deliveries for i in range(1,26)))
            self.assertTrue(all((root/'site'/t['profile']).is_file()for t in manifest['tracks']))
            self.assertEqual([r['rank']for r in health['report']if r.get('excluded')=='unavailable-or-analysis-failed'],[27,28])
            library=json.loads((root/'site/library.json').read_bytes())
            self.assertEqual(set(library['hot']),{t['assetId']for t in manifest['tracks']})

    def test_manual_growth_does_not_automatically_raise_twenty_and_explicit_thirty_works(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);self.setup_root(root,manual_count=10)
            manifest,health,_=self.run_build(root)
            self.assertEqual((health['chartEligible'],health['manualEligible']),(20,10))
            self.setup_root(root,target=30,manual_count=10)
            manifest,health,_=self.run_build(root)
            self.assertEqual((health['chartEligible'],health['manualEligible']),(30,10))
            self.assertEqual(max(t['chartRank']for t in manifest['tracks']),58)

    def test_insufficient_target_never_writes_a_new_manifest_or_advances_history(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);policy=self.setup_root(root);self.run_build(root)
            history=(root/'.cache/history.json').read_bytes()
            policy['excludedAssetIds']=list(range(1,86))
            (root/'selection-policy.json').write_text(json.dumps(policy))
            with self.assertRaisesRegex(AssertionError,'Chart target not met'):self.run_build(root)
            self.assertEqual((root/'.cache/history.json').read_bytes(),history)
            self.assertFalse((root/'site/manifest.json').exists())

    def test_chart_bounds_and_bad_api_responses_are_rejected(self):
        policy={'chartLimit':100,'chartTarget':20,'excludedArtists':[],'excludedWords':[],'excludedAssetIds':[]}
        for target in [True,0,-1,20.5,41,101]:
            with self.subTest(target=target),patch.object(publisher,'fetch')as fetch:
                with self.assertRaises(AssertionError):publisher.load_chart(dict(policy,chartTarget=target))
                fetch.assert_not_called()
        for rows in [[{'assetId':i}for i in range(99)],[{'assetId':1}]*100]:
            with patch.object(publisher,'fetch',return_value=json.dumps({'songs':rows}).encode()):
                with self.assertRaises(AssertionError):publisher.load_chart(policy)
        with self.assertRaises(AssertionError):publisher.load_chart(dict(policy,chartLimit=101))

    def test_manual_audio_failure_cannot_silently_remove_a_persistent_manual_song(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);self.setup_root(root);self.run_build(root)
            history=(root/'.cache/history.json').read_bytes()
            path=root/'manual-tracks.json';manual=json.loads(path.read_bytes())
            manual['tracks'].append({'assetId':27,'title':'Unavailable Manual','artist':'Artist','albumArtAssetId':0})
            path.write_text(json.dumps(manual))
            with self.assertRaisesRegex(AssertionError,'Manual song unavailable'):self.run_build(root)
            self.assertEqual((root/'.cache/history.json').read_bytes(),history)
            self.assertFalse((root/'site/manifest.json').exists())

    def test_old_policy_without_a_target_keeps_legacy_semantics(self):
        self.assertIsNone(publisher.chart_target({'chartLimit':40}))
        self.assertEqual(publisher.chart_target({'chartLimit':100,'chartTarget':30}),30)

if __name__=='__main__':unittest.main()
