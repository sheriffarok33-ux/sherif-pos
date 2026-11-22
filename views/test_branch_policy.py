"""Fixed branch environment policy. No database writes, authentication or sync hooks."""
import re

TEST_BRANCH_IDS = frozenset({7})

def _local_mode():
    from sherif_network import server_enabled
    if server_enabled():
        return False
    from offline_store import get_local_connection
    from sherif_local_identity import local_identity
    conn = get_local_connection(queue_writes=False)
    try:
        return local_identity(conn) is not None
    finally:
        conn.close()


def is_test_branch(branch_id):
    return not _local_mode() and branch_id is not None and int(branch_id) in TEST_BRANCH_IDS

def assert_transfer_environment(source_branch_id, target_branch_id):
    if source_branch_id is None or target_branch_id is None:
        raise ValueError('حدد فرع المصدر وفرع الاستلام.')
    if is_test_branch(source_branch_id) != is_test_branch(target_branch_id):
        raise ValueError('لا يمكن إنشاء تحويل بين فرع تجريبي وفرع إنتاج.')
    return True

def report_branch_ids(available, selected=None):
    ids={int(value) for value in available}
    if selected is not None:
        return {int(selected)} & ids
    production=ids if _local_mode() else ids-TEST_BRANCH_IDS
    return production

def expense_allocation_branches(branches, origin_branch_id=None):
    test=is_test_branch(origin_branch_id)
    return [row for row in branches if is_test_branch(row['id'])==test]

def report_predicate(selected=None, column='branch_id'):
    if not re.fullmatch(r'[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?',column):
        raise ValueError('Invalid report column')
    if selected is not None:
        return column+' = ?', (int(selected),)
    if _local_mode(): return '1=1', ()
    return '('+column+' IS NULL OR '+column+' <> ?)', (7,)

def production_overview(metrics, items):
    rows=[row for row in metrics if not is_test_branch(row['branch_id'])]
    totals={key:sum(float(row.get(key,0) or 0) for row in rows)
            for key in ('sales','invoice_count','expenses','revenues','purchases')}
    production_items=[row for row in items if not is_test_branch(row['branch_id'])]
    totals['stock_quantity']=sum(float(row.get('quantity',0) or 0) for row in production_items)
    totals['stock_cost']=sum(float(row.get('quantity',0) or 0)*(float(row.get('avg_cost') or 0) if float(row.get('avg_cost') or 0)>0 else float(row.get('buy_price') or 0)) for row in production_items)
    return totals
