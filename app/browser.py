"""使用真实 Chromium 浏览本地目录和详情。

read_visible_entry 保留原有导航验证；observe_visible_batch 进一步读取目录与
详情页面上的批次、版本、可约属性，并核对跳转后详情是否仍指向目录所选批次
（页面可能落到上一批次的缓存）。
"""
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright


def _check_origin(origin):
    url=urlsplit(origin)
    if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost'):raise ValueError('只允许本地页面')


def read_visible_entry(origin,item_id,edition='1'):
    _check_origin(origin)
    with sync_playwright() as engine:
        browser=engine.chromium.launch(headless=True)
        try:
            page=browser.new_page();page.goto(origin.rstrip('/')+'/catalog.html?edition='+str(edition))
            card=page.locator('article[data-id="'+item_id+'"]')
            if card.count()!=1:raise ValueError('目录身份不唯一')
            name=card.locator('h2').inner_text();card.locator('a').click()
            if page.locator('main').get_attribute('data-id')!=item_id:raise ValueError('详情身份不符')
            return {'id':item_id,'name':name,'url':page.url,'edition':page.locator('main').get_attribute('data-edition')}
        finally:browser.close()


def observe_visible_batch(origin,item_id,edition='1',stale=False):
    """从可见页面读取一条线路的批次信息，并检测缓存导致的批次错配。"""
    _check_origin(origin)
    suffix='&stale=1' if stale else ''
    with sync_playwright() as engine:
        browser=engine.chromium.launch(headless=True)
        try:
            page=browser.new_page()
            page.goto(origin.rstrip('/')+'/catalog.html?edition='+str(edition)+suffix)
            card=page.locator('article[data-id="'+item_id+'"]')
            if card.count()!=1:raise ValueError('目录身份不唯一')
            catalog_batch=card.locator('p[data-batch]').get_attribute('data-batch')
            card.locator('a').click()
            main=page.locator('main')
            if main.get_attribute('data-id')!=item_id:raise ValueError('详情身份不符')
            visible={
                'id':item_id,
                'url':page.url,
                'requested_edition':main.get_attribute('data-edition'),
                'served_revision':main.get_attribute('data-revision'),
                'catalog_batch_id':catalog_batch,
                'detail_batch_id':main.get_attribute('data-batch'),
                'detail_bookable':main.get_attribute('data-bookable')=='true',
                'same_batch':main.get_attribute('data-batch')==catalog_batch,
            }
            return visible
        finally:browser.close()
