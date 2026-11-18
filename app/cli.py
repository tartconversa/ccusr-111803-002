"""读取本地演练来源的公开资料，并运行可中断的一轮观察。

用法：
  python -m app.cli                 # 运行一轮观察并打印对账结果
  python -m app.cli --progress ID   # 查看某轮观察确认到哪一步
  python -m app.cli --batches       # 查看各批次当前状态与旧批次退役原因
  python -m app.cli --edition 2 [--stale] [--max-detail-edition 1]
"""
import argparse
import json
from pathlib import Path
from .capture import read_catalog,read_detail,observe_run
from . import records

DB_PATH=Path('data/records.sqlite3')
ORIGIN='http://127.0.0.1:8765'


def _print(value):
    print(json.dumps(value,ensure_ascii=False,indent=2))


def main(argv=None):
    parser=argparse.ArgumentParser(description='旅行线路资料采集与批次观察')
    parser.add_argument('--edition',default='1',choices=('1','2'))
    parser.add_argument('--run-id',default=None,help='观察运行标识；复用同一标识可续采')
    parser.add_argument('--stale',action='store_true',help='演练：页面跳转落到上一批次缓存')
    parser.add_argument('--max-detail-edition',type=int,default=None,choices=(1,2),
                        help='演练：详情最多发布到该版本，模拟详情更新晚于目录')
    parser.add_argument('--progress',metavar='RUN_ID',help='只查看某轮观察的进度')
    parser.add_argument('--batches',action='store_true',help='查看批次当前状态与退役原因')
    args=parser.parse_args(argv)

    if args.progress:
        view=records.run_progress(DB_PATH,args.progress)
        if view is None:raise SystemExit(f'未找到观察运行：{args.progress}')
        _print(view);return
    if args.batches:
        _print(records.batch_progress(DB_PATH));return

    run_id=args.run_id or f"run-edition-{args.edition}"
    try:
        view=observe_run(DB_PATH,ORIGIN,run_id,edition=args.edition,
                         stale=args.stale,max_detail_edition=args.max_detail_edition)
    except KeyboardInterrupt:
        print('采集中途退出，已保存当前进度：')
        view=records.run_progress(DB_PATH,run_id)
    _print(view)
    print('批次视图：')
    _print(records.batch_progress(DB_PATH))


if __name__=='__main__':main()
