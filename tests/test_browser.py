"""真实浏览器验证本地可控页面与缓存错批次检测。"""
import threading
import unittest
from app.site import DATA,start_server
from app.browser import read_visible_entry,observe_visible_batch

class BrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=start_server();cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.origin=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=2)
    def test_navigation(self):
        item=DATA['items'][0];entry=read_visible_entry(self.origin,item['id'])
        self.assertEqual(entry['name'],item['editions']['1']['catalog_name']);self.assertIn('/detail.html?',entry['url'])
    def test_visible_batch_matches(self):
        item=DATA['items'][0]
        visible=observe_visible_batch(self.origin,item['id'],edition='2')
        self.assertTrue(visible['same_batch'])
        self.assertEqual(visible['catalog_batch_id'],'travel-a-batch-2')
        self.assertEqual(visible['detail_batch_id'],'travel-a-batch-2')
        self.assertEqual(visible['served_revision'],'2')
    def test_stale_cache_detected_in_browser(self):
        item=DATA['items'][0]
        visible=observe_visible_batch(self.origin,item['id'],edition='2',stale=True)
        self.assertFalse(visible['same_batch'])
        self.assertEqual(visible['catalog_batch_id'],'travel-a-batch-2')
        self.assertEqual(visible['detail_batch_id'],'travel-a-batch-1')
        self.assertEqual(visible['served_revision'],'1')


if __name__=='__main__':
    unittest.main()
