"""保存采集收据、观察结论与批次生命周期。

旧表 catalog/details/progress 与旧函数保持不变，供既有流程使用。
新增五张表支撑一轮完整观察：
- runs：一轮观察的运行状态（进行中/已完成/已中断），可按 run_id 续采；
- run_steps：每个来源读取到哪一步的流水；
- source_receipts：每处来源的版本收据（URL、请求版本、实际服务修订、原始载荷）；
- observations：线路×批次的对账结论，incomplete 与 verified 同等保留；
- batches：每个出发批次的当前状态，以及旧批次不再可用的原因。
"""
import json
import sqlite3
from datetime import datetime,timezone
from pathlib import Path


def _now():
    return datetime.now(timezone.utc).isoformat()


def connect(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(path)
    # 既有表（基础收据流程）。
    db.execute('CREATE TABLE IF NOT EXISTS catalog (source_id TEXT PRIMARY KEY,edition TEXT NOT NULL,payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS details (receipt INTEGER PRIMARY KEY,source_id TEXT NOT NULL,edition TEXT NOT NULL,payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS progress (name TEXT PRIMARY KEY,last_page TEXT NOT NULL)')
    # 一轮观察相关表。
    db.execute('CREATE TABLE IF NOT EXISTS runs ('
               'run_id TEXT PRIMARY KEY,origin TEXT NOT NULL,edition TEXT NOT NULL,'
               'state TEXT NOT NULL,started_at TEXT NOT NULL,finished_at TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS run_steps ('
               'step_id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,'
               'stage TEXT NOT NULL,source_id TEXT,status TEXT NOT NULL,note TEXT,at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS source_receipts ('
               'receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT NOT NULL,'
               'source_kind TEXT NOT NULL,source_id TEXT NOT NULL,'
               'requested_edition TEXT NOT NULL,served_revision TEXT NOT NULL,'
               'url TEXT NOT NULL,payload TEXT NOT NULL,at TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS observations ('
               'run_id TEXT NOT NULL,source_id TEXT NOT NULL,edition TEXT NOT NULL,'
               'batch_id TEXT NOT NULL,status TEXT NOT NULL,reason TEXT,'
               'bookable INTEGER,catalog_receipt_id INTEGER,detail_receipt_id INTEGER,'
               'updated_at TEXT NOT NULL,PRIMARY KEY (run_id,source_id))')
    db.execute('CREATE TABLE IF NOT EXISTS batches ('
               'batch_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,edition TEXT NOT NULL,'
               'status TEXT NOT NULL,bookable INTEGER,active INTEGER NOT NULL,'
               'retired_reason TEXT,first_run_id TEXT NOT NULL,last_run_id TEXT NOT NULL,'
               'updated_at TEXT NOT NULL)')
    return db


# ---------------------------------------------------------------- 既有接口

def save_catalog(path,result):
    db=connect(path)
    try:
        for item in result['items']:db.execute('INSERT OR REPLACE INTO catalog VALUES (?,?,?)',(item['id'],result['edition'],json.dumps(item,ensure_ascii=False)))
        db.execute('INSERT OR REPLACE INTO progress VALUES (?,?)',('catalog',result['url']))
        db.commit()
    finally:db.close()
    return len(result['items'])


def save_detail(path,result):
    item=result['item']
    db=connect(path)
    try:
        db.execute('INSERT INTO details (source_id,edition,payload) VALUES (?,?,?)',(item['id'],result['edition'],json.dumps(result,ensure_ascii=False)))
        db.execute('INSERT OR REPLACE INTO progress VALUES (?,?)',('detail',result['url']))
        db.commit()
    finally:db.close()
    return item['id']


def list_receipts(path):
    db=connect(path)
    try:return [json.loads(row[0]) for row in db.execute('SELECT payload FROM details ORDER BY receipt')]
    finally:db.close()


# ---------------------------------------------------------------- 观察运行

def start_run(path,run_id,origin,edition):
    db=connect(path)
    try:
        row=db.execute('SELECT run_id,state FROM runs WHERE run_id=?',(run_id,)).fetchone()
        if row is None:
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?)',(run_id,origin,str(edition),'in_progress',_now(),None))
            db.commit();state='in_progress'
        else:
            state=row[1]
        return {'run_id':run_id,'state':state}
    finally:db.close()


def get_run(path,run_id):
    db=connect(path)
    try:
        row=db.execute('SELECT run_id,origin,edition,state,started_at,finished_at FROM runs WHERE run_id=?',(run_id,)).fetchone()
        if row is None:return None
        return dict(zip(('run_id','origin','edition','state','started_at','finished_at'),row))
    finally:db.close()


def finish_run(path,run_id,state):
    db=connect(path)
    try:
        db.execute('UPDATE runs SET state=?,finished_at=? WHERE run_id=?',(state,_now(),run_id))
        db.commit()
    finally:db.close()


def add_step(path,run_id,stage,status,source_id=None,note=None):
    db=connect(path)
    try:
        db.execute('INSERT INTO run_steps (run_id,stage,source_id,status,note,at) VALUES (?,?,?,?,?,?)',
                   (run_id,stage,source_id,status,note,_now()))
        db.commit()
    finally:db.close()


def insert_receipt(path,run_id,source_kind,source_id,requested_edition,served_revision,url,payload):
    db=connect(path)
    try:
        cursor=db.execute(
            'INSERT INTO source_receipts (run_id,source_kind,source_id,requested_edition,served_revision,url,payload,at)'
            ' VALUES (?,?,?,?,?,?,?,?)',
            (run_id,source_kind,source_id,str(requested_edition),str(served_revision),url,
             json.dumps(payload,ensure_ascii=False),_now()))
        db.commit()
        return cursor.lastrowid
    finally:db.close()


def refresh_catalog_receipt(path,run_id,source_id,catalog_receipt_id):
    """续采时只替换目录收据引用，保留上一轮已核实的观察结论。"""
    db=connect(path)
    try:
        db.execute('UPDATE observations SET catalog_receipt_id=?,updated_at=? '
                   'WHERE run_id=? AND source_id=?',
                   (catalog_receipt_id,_now(),run_id,source_id))
        db.commit()
    finally:db.close()


def latest_receipt_id(path,run_id,source_kind,source_id):
    db=connect(path)
    try:
        row=db.execute(
            'SELECT receipt_id FROM source_receipts WHERE run_id=? AND source_kind=? AND source_id=? '
            'ORDER BY receipt_id DESC LIMIT 1',(run_id,source_kind,source_id)).fetchone()
        return row[0] if row else None
    finally:db.close()


def upsert_observation(path,run_id,source_id,edition,batch_id,status,reason,bookable,
                       catalog_receipt_id,detail_receipt_id):
    db=connect(path)
    try:
        db.execute(
            'INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?) '
            'ON CONFLICT(run_id,source_id) DO UPDATE SET edition=excluded.edition,'
            'batch_id=excluded.batch_id,status=excluded.status,reason=excluded.reason,'
            'bookable=excluded.bookable,catalog_receipt_id=excluded.catalog_receipt_id,'
            'detail_receipt_id=excluded.detail_receipt_id,updated_at=excluded.updated_at',
            (run_id,source_id,str(edition),batch_id,status,reason,
             None if bookable is None else int(bookable),
             catalog_receipt_id,detail_receipt_id,_now()))
        db.commit()
    finally:db.close()


def upsert_batch(path,source_id,batch_id,edition,status,bookable,active,retired_reason,run_id):
    db=connect(path)
    try:
        db.execute(
            'INSERT INTO batches VALUES (?,?,?,?,?,?,?,?,?,?) '
            'ON CONFLICT(batch_id) DO UPDATE SET status=excluded.status,'
            'bookable=excluded.bookable,active=excluded.active,'
            'retired_reason=excluded.retired_reason,'
            'last_run_id=excluded.last_run_id,updated_at=excluded.updated_at',
            (batch_id,source_id,str(edition),status,
             None if bookable is None else int(bookable),
             int(active),retired_reason,run_id,run_id,_now()))
        db.commit()
    finally:db.close()


def retire_other_batches(path,source_id,keep_batch_id,reason,run_id):
    """同一线路除 keep_batch_id 外仍活跃的批次一律退役，并记录原因。"""
    db=connect(path)
    try:
        db.execute(
            'UPDATE batches SET active=0,retired_reason=?,last_run_id=?,updated_at=? '
            'WHERE source_id=? AND batch_id<>? AND active=1',
            (reason,run_id,_now(),source_id,keep_batch_id))
        db.commit()
    finally:db.close()


# ---------------------------------------------------------------- 客服查询

def run_progress(path,run_id):
    """一轮观察目前确认到哪一步：运行头、步骤流水、每条线路的观察结论。"""
    run=get_run(path,run_id)
    if run is None:return None
    db=connect(path)
    try:
        steps=[dict(zip(('step_id','stage','source_id','status','note','at'),row))
               for row in db.execute(
                   'SELECT step_id,stage,source_id,status,note,at FROM run_steps WHERE run_id=? ORDER BY step_id',
                   (run_id,))]
        observations=[dict(zip(('source_id','edition','batch_id','status','reason','bookable',
                                'catalog_receipt_id','detail_receipt_id','updated_at'),row))
                      for row in db.execute(
                          'SELECT source_id,edition,batch_id,status,reason,bookable,'
                          'catalog_receipt_id,detail_receipt_id,updated_at FROM observations '
                          'WHERE run_id=? ORDER BY source_id',(run_id,))]
        receipts=[dict(zip(('receipt_id','source_kind','source_id','requested_edition',
                            'served_revision','url','at'),row))
                  for row in db.execute(
                      'SELECT receipt_id,source_kind,source_id,requested_edition,served_revision,url,at '
                      'FROM source_receipts WHERE run_id=? ORDER BY receipt_id',(run_id,))]
    finally:db.close()
    for observation in observations:
        observation['bookable']=None if observation['bookable'] is None else bool(observation['bookable'])
    return {**run,'steps':steps,'observations':observations,'receipts':receipts}


def batch_progress(path):
    """所有批次的当前状态；active=0 的行带 retired_reason，解释旧批次为何不可用。"""
    db=connect(path)
    try:
        rows=[dict(zip(('batch_id','source_id','edition','status','bookable','active',
                        'retired_reason','first_run_id','last_run_id','updated_at'),row))
              for row in db.execute(
                  'SELECT batch_id,source_id,edition,status,bookable,active,'
                  'retired_reason,first_run_id,last_run_id,updated_at FROM batches '
                  'ORDER BY source_id,active DESC,batch_id')]
    finally:db.close()
    for row in rows:
        row['bookable']=None if row['bookable'] is None else bool(row['bookable'])
        row['active']=bool(row['active'])
    return rows


def verified_source_ids(path,run_id):
    """本轮已经对过账并核实的线路，续采时可以跳过；不完整观察不在此列。"""
    db=connect(path)
    try:
        return {row[0] for row in db.execute(
            "SELECT source_id FROM observations WHERE run_id=? AND status='verified'",
            (run_id,))}
    finally:db.close()
