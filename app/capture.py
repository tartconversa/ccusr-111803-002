"""从本地来源获取目录和单项详情，并编排一轮可中断、可续采的观察。

一轮 observe_run 按“目录 → 逐线路详情 → 批次对账 → 批次退役”推进，
每个来源读取后立即写收据与步骤流水。中断（KeyboardInterrupt/异常）后用同一
run_id 再次调用即可续采：上一轮已 verified 的线路跳过详情重读，incomplete
的线路重新采集对账。
"""
import json
from urllib.parse import urlencode,urlsplit
from urllib.request import urlopen
from .domain import interpret_catalog,interpret_detail,reconcile_batch,RETIRED_SUPERSEDED
from . import records


def get(origin,path,query):
    url=urlsplit(origin)
    if url.scheme!='http' or url.hostname not in ('127.0.0.1','localhost'):raise ValueError('只允许本地演练来源')
    params={key:value for key,value in query.items() if value is not None}
    address=origin.rstrip('/')+path+'?'+urlencode(params)
    with urlopen(address,timeout=5) as response:data=json.load(response)
    return address,data


def read_catalog(origin,edition='1'):
    address,data=get(origin,'/catalog',{'edition':edition})
    return {'url':address,'edition':data['edition'],'items':[dict(item,identity=interpret_catalog(item)) for item in data['items']]}


def read_detail(origin,item_id,edition='1',stale=False,max_detail_edition=None):
    address,data=get(origin,'/detail',{
        'id':item_id,'edition':edition,
        'stale':'1' if stale else None,
        'max_detail_edition':max_detail_edition,
    })
    return {'url':address,'edition':data['edition'],'item':dict(data,identity=interpret_detail(data))}


def observe_run(db_path,origin,run_id,edition='1',stale=False,max_detail_edition=None):
    """执行一轮观察并返回 run_progress 视图。

    stale/max_detail_edition 是演练来源的两个故障开关；真实采集时两者缺省。
    目录读成功后才会逐条读详情，因此中断时至少保留目录阶段的完整收据。
    """
    edition=str(edition)
    records.start_run(db_path,run_id,origin,edition)
    try:
        catalog=read_catalog(origin,edition)
        already_verified=records.verified_source_ids(db_path,run_id)
        catalog_receipt={}
        for item in catalog['items']:
            receipt_id=records.insert_receipt(
                db_path,run_id,'catalog',item['id'],edition,catalog['edition'],
                catalog['url'],item)
            catalog_receipt[item['id']]=receipt_id
            if item['id'] in already_verified:
                # 续采：上一轮已核实的线路保留原结论，只更新目录收据引用。
                records.refresh_catalog_receipt(db_path,run_id,item['id'],receipt_id)
                continue
            # 详情未到之前先落一条不完整观察，绝不提前声称可约。
            records.upsert_observation(
                db_path,run_id,item['id'],edition,item['identity']['batch_id'],
                'incomplete','detail_missing',None,receipt_id,None)
        records.add_step(db_path,run_id,'catalog','ok',
                         note=f'{len(catalog["items"])} 条线路目录收据已保存')

        done=records.verified_source_ids(db_path,run_id)
        for item in catalog['items']:
            source_id=item['id']
            if source_id in done:
                records.add_step(db_path,run_id,'detail','skipped',source_id,'续采：上一轮已核实，跳过详情重读')
                continue
            try:
                detail=read_detail(origin,source_id,edition,
                                   stale=stale,max_detail_edition=max_detail_edition)
            except Exception as exc:  # 单条详情失败不抹掉已有观察，留待下一轮续采。
                records.add_step(db_path,run_id,'detail','error',source_id,str(exc))
                continue
            payload=detail['item']
            detail_receipt=records.insert_receipt(
                db_path,run_id,'detail',source_id,
                payload['identity']['requested_edition'],payload['identity']['revision'],
                detail['url'],payload)
            records.add_step(db_path,run_id,'detail','ok',source_id,
                             f"请求版本 {payload['identity']['requested_edition']}，"
                             f"实际服务修订 {payload['identity']['revision']}")

            verdict=reconcile_batch(item['identity'],payload['identity'])
            records.upsert_observation(
                db_path,run_id,source_id,edition,verdict['batch_id'],
                verdict['status'],verdict['reason'],verdict['bookable'],
                catalog_receipt[source_id],detail_receipt)
            records.add_step(db_path,run_id,'reconcile',verdict['status'],source_id,
                             verdict['reason'] or '同批次一致')

            # 只有对过账的批次才能进入批次视图；不完整观察保留，但不代表批次可用。
            active=verdict['status']=='verified'
            records.upsert_batch(
                db_path,source_id,verdict['batch_id'],edition,
                verdict['status'],verdict['bookable'],active,
                None if active else verdict['reason'],run_id)
            if active:
                # 新批次核实成功，同线路的旧批次立即退役并写明原因。
                records.retire_other_batches(db_path,source_id,verdict['batch_id'],
                                             RETIRED_SUPERSEDED,run_id)

        records.finish_run(db_path,run_id,'completed')
    except KeyboardInterrupt:
        records.add_step(db_path,run_id,'run','interrupted',note='采集中途退出，已保存的收据与观察保留')
        records.finish_run(db_path,run_id,'interrupted')
        raise
    except Exception as exc:
        records.add_step(db_path,run_id,'run','failed',note=repr(exc))
        records.finish_run(db_path,run_id,'failed')
        raise
    return records.run_progress(db_path,run_id)
