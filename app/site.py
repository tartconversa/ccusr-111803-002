"""供采集程序读取的本地演练来源。

目录与详情都带发布期 edition。详情支持两个演练开关：
- stale=1：模拟页面跳转落到上一批次的缓存，详情仍返回上一批次内容；
- max_detail_edition：模拟详情更新晚于目录，请求高于该值的发布期时，
  详情仍给出上一发布期，并在 served_revision 中如实标注实际服务的版本。
"""
import json
from html import escape
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs,urlsplit

DATA=json.loads((Path(__file__).resolve().parents[1]/'fixtures'/'source.json').read_text(encoding='utf-8'))

def _period(item,edition):
    return item['editions'][edition]

def catalog(edition):
    rows=[]
    for item in DATA['items']:
        period=_period(item,edition);batch=period['batch']
        rows.append({
            'id':item['id'],'name':period['catalog_name'],'group':item['group'],
            'summary':period['detail']['terms'],
            'edition':edition,
            'batch_id':batch['batch_id'],'batch_label':batch['label'],
            'bookable':batch['bookable'],
        })
    return {'edition':edition,'items':rows}

def detail(item,edition,stale=False,max_detail_edition=None):
    served_edition=edition
    if stale:
        # 上一批次缓存：只有第二发布期存在“上一批次”可回退。
        served_edition='1' if edition=='2' else edition
    elif max_detail_edition is not None and int(edition)>max_detail_edition:
        # 详情发布滞后：只能提供上一发布期的详情。
        served_edition=str(max_detail_edition)
    period=_period(item,served_edition);info=period['detail']
    return {
        'id':item['id'],'name':period['catalog_name'],'group':item['group'],
        'edition':edition,'revision':served_edition,
        'requested_edition':edition,'served_revision':served_edition,
        'stale':stale,
        'batch_id':info['batch_id'],'batch_label':period['batch']['label'],
        'meeting_point':info['meeting_point'],'terms':info['terms'],
        'bookable':info['bookable'],
        'detail':info['terms'],
    }

def catalog_page(edition,stale=False):
    suffix='&stale=1' if stale else ''
    cards=''.join(
        '<article data-id="'+escape(x['id'])+'"><h2>'+escape(_period(x,edition)['catalog_name'])+'</h2>'
        '<p data-batch="'+escape(_period(x,edition)['batch']['batch_id'])+'">'+escape(DATA['choice'])+'：'+escape(_period(x,edition)['batch']['label'])+'</p>'
        '<a href="/detail.html?id='+escape(x['id'])+'&edition='+edition+suffix+'">查看详情</a></article>'
        for x in DATA['items'])
    return '<html lang="zh"><meta charset="utf-8"><h1>'+escape(DATA['title'])+'</h1><main data-edition="'+edition+'">'+cards+'</main></html>'

def detail_page(item,edition,stale=False,max_detail_edition=None):
    info=detail(item,edition,stale=stale,max_detail_edition=max_detail_edition)
    state=escape('可约' if info['bookable'] else '不可约')
    return ('<html lang="zh"><meta charset="utf-8"><h1>'+escape(info['name'])+'</h1>'
            '<main data-id="'+escape(info['id'])+'" data-edition="'+edition+'" '
            'data-revision="'+escape(info['served_revision'])+'" '
            'data-batch="'+escape(info['batch_id'])+'" data-bookable="'+('true' if info['bookable'] else 'false')+'">'
            '<label>'+escape(DATA['choice'])+'<select id="choice"><option>'+escape(info['batch_label'])+'</option></select></label>'
            '<button id="show">查看'+escape(DATA['detail_label'])+'</button>'
            '<section id="result"></section><p>集合地点：'+escape(info['meeting_point'])+'</p>'
            '<p>可约状态：'+state+'</p>'
            '<p>'+escape(DATA['revision'])+' '+escape(info['served_revision'])+'</p></main>'
            '<script>document.querySelector("#show").onclick=()=>{document.querySelector("#result").textContent='
            +json.dumps(info['terms'],ensure_ascii=False)+'}</script></html>')

def _as_bool(text):
    return text in ('1','true','yes')

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url=urlsplit(self.path);args=parse_qs(url.query);edition=args.get('edition',['1'])[0]
        if edition not in ('1','2'):self.send_error(400);return
        stale=_as_bool(args.get('stale',['0'])[0])
        max_edition=args.get('max_detail_edition',[None])[0]
        max_detail_edition=int(max_edition) if max_edition in ('1','2') else None
        if url.path in ('/catalog','/catalog.html'):
            body=catalog_page(edition,stale=stale) if url.path.endswith('.html') else json.dumps(catalog(edition),ensure_ascii=False)
        elif url.path in ('/detail','/detail.html'):
            item=next((x for x in DATA['items'] if x['id']==args.get('id',[''])[0]),None)
            if item is None:self.send_error(404);return
            body=(detail_page(item,edition,stale=stale,max_detail_edition=max_detail_edition) if url.path.endswith('.html')
                  else json.dumps(detail(item,edition,stale=stale,max_detail_edition=max_detail_edition),ensure_ascii=False))
        else:self.send_error(404);return
        raw=body.encode('utf-8');self.send_response(200);self.send_header('Content-Type',('text/html' if url.path.endswith('.html') else 'application/json')+'; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def log_message(self,*args):pass

def start_server():return ThreadingHTTPServer(('127.0.0.1',0),Handler)

if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',8765),Handler);print('本地来源：http://127.0.0.1:8765/catalog',flush=True);server.serve_forever()
