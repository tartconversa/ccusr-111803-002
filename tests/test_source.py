"""本地来源、批次对账与观察记录的回归。"""
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen
from app.site import DATA,start_server
from app.capture import read_catalog,read_detail,observe_run
from app.domain import (reconcile_batch,interpret_catalog,interpret_detail,
                        VERIFIED,INCOMPLETE,REASON_BATCH_MISMATCH,REASON_REVISION_LAG,
                        REASON_DETAIL_MISSING,RETIRED_SUPERSEDED)
from app.records import (save_catalog,save_detail,list_receipts,
                         run_progress,batch_progress)


class SourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=start_server();cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.origin=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=2)

    def _db(self,root):
        return Path(root)/'records.sqlite3'

    def test_catalog_and_detail(self):
        items=read_catalog(self.origin)['items'];self.assertEqual(len(items),len(DATA['items']))
        for item in items:
            self.assertIn('batch_id',item['identity'])
            detail=read_detail(self.origin,item['id'])['item']
            self.assertEqual(detail['id'],item['id'])
            self.assertEqual(detail['served_revision'],detail['requested_edition'])

    def test_revision_and_page(self):
        key=DATA['items'][0]['id']
        self.assertNotEqual(read_detail(self.origin,key,'1')['item']['detail'],read_detail(self.origin,key,'2')['item']['detail'])
        with urlopen(self.origin+'/catalog.html?edition=2') as response:self.assertIn(DATA['title'],response.read().decode('utf-8'))

    def test_legacy_receipts_kept(self):
        # 既有基础收据流程必须保持可用。
        with tempfile.TemporaryDirectory() as temporary:
            path=self._db(temporary);catalog=read_catalog(self.origin)
            self.assertEqual(save_catalog(path,catalog),2)
            save_detail(path,read_detail(self.origin,catalog['items'][0]['id']))
            self.assertEqual(len(list_receipts(path)),1)

    def test_remote_rejected(self):
        with self.assertRaises(ValueError):read_catalog('https://example.com')

    def test_verified_run_links_route_batch_terms_and_bookable(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=self._db(temporary)
            view=observe_run(path,self.origin,'run-ok',edition='1')
            self.assertEqual(view['state'],'completed')
            self.assertEqual({o['status'] for o in view['observations']},{VERIFIED})
            first=next(o for o in view['observations'] if o['source_id']=='travel-a')
            self.assertEqual(first['batch_id'],'travel-a-batch-1')
            self.assertTrue(first['bookable'])
            # 每处来源都留有带版本的收据。
            kinds={r['source_kind'] for r in view['receipts']}
            self.assertEqual(kinds,{'catalog','detail'})
            self.assertTrue(all(r['served_revision']==r['requested_edition'] for r in view['receipts']))
            # 批次视图可被客服直接读取。
            batches=batch_progress(path)
            self.assertTrue(all(b['active'] for b in batches))

    def test_stale_cache_keeps_incomplete_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=self._db(temporary)
            view=observe_run(path,self.origin,'run-stale',edition='2',stale=True)
            by_id={o['source_id']:o for o in view['observations']}
            # travel-a 改期换批次：缓存页落在上一批次，批次错配。
            self.assertEqual(by_id['travel-a']['status'],INCOMPLETE)
            self.assertEqual(by_id['travel-a']['reason'],REASON_BATCH_MISMATCH)
            self.assertIsNone(by_id['travel-a']['bookable'])
            # travel-b 同批次改条款：缓存页是同批次的旧版本，版本滞后。
            self.assertEqual(by_id['travel-b']['status'],INCOMPLETE)
            self.assertEqual(by_id['travel-b']['reason'],REASON_REVISION_LAG)
            # 目录本身仍声称可约，收据保留了这个矛盾现场。
            stale_detail=read_detail(self.origin,'travel-a','2',stale=True)['item']
            self.assertEqual(stale_detail['identity']['batch_id'],'travel-a-batch-1')
            self.assertEqual(by_id['travel-a']['batch_id'],'travel-a-batch-2')
            # 不完整观察不得产生活跃（已核实）批次，也不得写出可约结论。
            self.assertTrue(all(not b['active'] for b in batch_progress(path)))
            self.assertTrue(all(o['bookable'] is None for o in view['observations']))

    def test_detail_lag_keeps_incomplete_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=self._db(temporary)
            # 目录已是第二发布期，详情最多只发布到第一期。
            view=observe_run(path,self.origin,'run-lag',edition='2',max_detail_edition=1)
            by_id={o['source_id']:o for o in view['observations']}
            # travel-b 两期沿用同一批次：批次号一致、仅版本落后，是纯粹的详情滞后。
            self.assertEqual(by_id['travel-b']['status'],INCOMPLETE)
            self.assertEqual(by_id['travel-b']['reason'],REASON_REVISION_LAG)
            self.assertIsNone(by_id['travel-b']['bookable'])
            # travel-a 第二期已换批次，滞后的详情同时指向旧批次。
            self.assertEqual(by_id['travel-a']['reason'],REASON_BATCH_MISMATCH)
            # 无论哪种原因，都不得留下“已核实可约”。
            self.assertTrue(all(o['status']==INCOMPLETE for o in view['observations']))
            lagged=read_detail(self.origin,'travel-b','2',max_detail_edition=1)['item']
            self.assertEqual(lagged['served_revision'],'1')
            self.assertEqual(lagged['requested_edition'],'2')

    def test_reconcile_rules_unit(self):
        catalog_row={'id':'travel-a','name':'x','group':'甲','edition':'2',
                     'batch_id':'b2','bookable':True}
        identity=interpret_catalog(catalog_row)
        # 没有详情时只能是不完整观察。
        waiting=reconcile_batch(identity)
        self.assertEqual(waiting['status'],INCOMPLETE)
        self.assertEqual(waiting['reason'],REASON_DETAIL_MISSING)
        # 同批次同版本同状态才可核实。
        ok=interpret_detail({'id':'travel-a','revision':'2','requested_edition':'2',
                             'group':'甲','batch_id':'b2','bookable':True,
                             'meeting_point':'东门','terms':'新条款'})
        self.assertEqual(reconcile_batch(identity,ok)['status'],VERIFIED)
        # 版本滞后单独成因。
        lag=dict(ok);lag['revision']='1'
        self.assertEqual(reconcile_batch(identity,interpret_detail(
            {'id':'travel-a','revision':'1','requested_edition':'2','group':'甲',
             'batch_id':'b2','bookable':True}))['reason'],REASON_REVISION_LAG)
        # 可约状态冲突也不能核实。
        conflict=interpret_detail({'id':'travel-a','revision':'2','requested_edition':'2',
                                   'group':'甲','batch_id':'b2','bookable':False})
        self.assertEqual(reconcile_batch(identity,conflict)['status'],INCOMPLETE)

    def test_interrupted_run_resumes_and_keeps_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=self._db(temporary)
            # 第一轮只完成目录阶段后中断。
            first=observe_run(path,self.origin,'run-resume',edition='1')
            self.assertEqual(first['state'],'completed')
            # 模拟中断：直接删除某条详情收据，再以同一 run_id 续采。
            import sqlite3
            with sqlite3.connect(path) as db:
                db.execute("DELETE FROM source_receipts WHERE run_id=? AND source_kind='detail' AND source_id='travel-b'",
                           ('run-resume',))
                db.execute("UPDATE observations SET status='incomplete',reason='detail_missing',"
                           "detail_receipt_id=NULL,bookable=NULL WHERE run_id=? AND source_id='travel-b'",
                           ('run-resume',))
                db.commit()
            mid=run_progress(path,'run-resume')
            self.assertEqual(next(o for o in mid['observations'] if o['source_id']=='travel-b')['reason'],
                             'detail_missing')
            resumed=observe_run(path,self.origin,'run-resume',edition='1')
            self.assertEqual(resumed['state'],'completed')
            statuses={o['source_id']:o['status'] for o in resumed['observations']}
            self.assertEqual(set(statuses.values()),{VERIFIED})
            skipped=[s for s in resumed['steps'] if s['status']=='skipped']
            self.assertTrue(skipped,'已有详情收据的线路应在续采时跳过')

    def test_superseded_batch_is_retired_with_reason(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=self._db(temporary)
            observe_run(path,self.origin,'run-e1',edition='1')
            first_batches={b['batch_id']:b for b in batch_progress(path)}
            self.assertTrue(first_batches['travel-a-batch-1']['active'])
            observe_run(path,self.origin,'run-e2',edition='2')
            final={b['batch_id']:b for b in batch_progress(path)}
            self.assertFalse(final['travel-a-batch-1']['active'])
            self.assertEqual(final['travel-a-batch-1']['retired_reason'],RETIRED_SUPERSEDED)
            self.assertTrue(final['travel-a-batch-2']['active'])
            # 旧批次的收据仍可追溯，没有被按名称覆盖。
            view=run_progress(path,'run-e1')
            self.assertTrue(any(r['source_id']=='travel-a' and r['source_kind']=='detail'
                                for r in view['receipts']))


    def test_recovered_run_reactivates_batch_after_incomplete_round(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=self._db(temporary)
            # 第一轮被缓存所阻：新批次只能以不完整观察存在且不活跃。
            observe_run(path,self.origin,'run-stale-first',edition='2',stale=True)
            stalled={b['batch_id']:b for b in batch_progress(path)}
            self.assertFalse(stalled['travel-a-batch-2']['active'])
            # 再次采集、来源恢复一致：同一批次应转为已核实并重新激活。
            observe_run(path,self.origin,'run-healthy',edition='2')
            healed={b['batch_id']:b for b in batch_progress(path)}
            self.assertTrue(healed['travel-a-batch-2']['active'])
            self.assertEqual(healed['travel-a-batch-2']['status'],VERIFIED)
            self.assertIsNone(healed['travel-a-batch-2']['retired_reason'])
            # 不完整轮从未让 batch-1 进入批次视图，客服看不到“幽灵批次”。
            self.assertNotIn('travel-a-batch-1',healed)


if __name__=='__main__':
    unittest.main()
