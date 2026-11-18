"""解释目录与详情的业务身份，并对同一条线路的两个来源做批次级对账。

对账只承认稳定标识：线路用 source_id，批次用 batch_id，发布期用 edition。
显示名称只用于展示，不能作为覆盖键，避免“新日期配旧条款”。
"""

# 对账结论：
# verified   —— 目录与详情可证明属于同一线路、同一出发批次、同一发布版本，
#               且两边可约状态一致；只有该结论才能对外称为“已核实可约/不可约”。
# incomplete —— 来源之间无法证明同批次一致，观察保留但不完整，附带原因。
VERIFIED='verified'
INCOMPLETE='incomplete'

# 不完整观察的具体原因。
REASON_DETAIL_MISSING='detail_missing'                 # 只读到目录，详情尚未采集
REASON_BATCH_MISMATCH='batch_mismatch'                 # 页面落到上一批次缓存
REASON_REVISION_LAG='detail_revision_lag'              # 详情更新晚于目录
REASON_BOOKABLE_CONFLICT='bookable_conflict'           # 两边可约状态不一致
REASON_IDENTITY_MISMATCH='identity_mismatch'           # 线路稳定标识不一致

# 旧批次不可用的原因。
RETIRED_SUPERSEDED='superseded_by_new_batch'           # 改期后由新批次接替
RETIRED_NOT_BOOKABLE='not_bookable'                    # 来源显示该批次不可约


def interpret_catalog(row):
    if not row['id'] or not row['name']:raise ValueError('目录身份不完整')
    if not row.get('batch_id'):raise ValueError('目录批次身份不完整')
    return {
        'source_id':row['id'],'group':row['group'],'name':row['name'],
        'edition':str(row['edition']),'batch_id':row['batch_id'],
        'bookable':bool(row['bookable']),
    }


def interpret_detail(row):
    if not row['id'] or row['revision'] not in ('1','2'):raise ValueError('详情身份不完整')
    if not row.get('batch_id'):raise ValueError('详情批次身份不完整')
    return {
        'source_id':row['id'],'group':row['group'],'revision':str(row['revision']),
        'requested_edition':str(row.get('requested_edition',row['revision'])),
        'batch_id':row['batch_id'],'bookable':bool(row['bookable']),
        'meeting_point':row.get('meeting_point'),'terms':row.get('terms'),
    }


def reconcile_batch(catalog_identity,detail_identity=None):
    """把同一线路的目录观察与详情观察对账为一条批次观察。

    返回 dict：status、reason（incomplete 时非空）、batch_id、bookable、
    以及参与对账的两份身份快照。任何无法证明同批次一致的情形都保持
    incomplete，调用方不得把它写成已核实可约。
    """
    catalog_identity=dict(catalog_identity)
    base={
        'source_id':catalog_identity['source_id'],
        'edition':catalog_identity['edition'],
        'catalog_batch_id':catalog_identity['batch_id'],
        'catalog_bookable':catalog_identity['bookable'],
        'detail':None,
        'batch_id':catalog_identity['batch_id'],
        'bookable':None,
    }
    if detail_identity is None:
        return {**base,'status':INCOMPLETE,'reason':REASON_DETAIL_MISSING}

    detail_identity=dict(detail_identity)
    base['detail']=detail_identity
    base['detail_batch_id']=detail_identity['batch_id']
    base['detail_bookable']=detail_identity['bookable']

    if detail_identity['source_id']!=catalog_identity['source_id']:
        return {**base,'status':INCOMPLETE,'reason':REASON_IDENTITY_MISMATCH}
    # 批次不一致是最强信号：详情指向另一个批次（典型为上一批次缓存），
    # 即使它同时带着旧版本，也不能并入当前批次。
    if detail_identity['batch_id']!=catalog_identity['batch_id']:
        return {**base,'status':INCOMPLETE,'reason':REASON_BATCH_MISMATCH}
    if detail_identity['revision']!=catalog_identity['edition']:
        # 同批次但详情实际服务的发布期落后于目录，条款可能仍是旧版本。
        return {**base,'status':INCOMPLETE,'reason':REASON_REVISION_LAG}
    if detail_identity['bookable']!=catalog_identity['bookable']:
        return {**base,'status':INCOMPLETE,'reason':REASON_BOOKABLE_CONFLICT}

    return {
        **base,'status':VERIFIED,'reason':None,
        'batch_id':catalog_identity['batch_id'],
        'bookable':catalog_identity['bookable'],
    }


def retirement_reason(previous_batch,current_batch):
    """判断同一线路的旧批次为何不再可用。

    previous_batch/current_batch 为批次记录（含 batch_id、edition、bookable）。
    不同批次标识视为改期接替；同一批次但来源显示不可约则记为不可约。
    """
    if previous_batch['batch_id']!=current_batch['batch_id']:
        return RETIRED_SUPERSEDED
    if previous_batch.get('bookable') and not current_batch.get('bookable'):
        return RETIRED_NOT_BOOKABLE
    return None
