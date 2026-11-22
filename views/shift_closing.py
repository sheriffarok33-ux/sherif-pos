"""Validate a fresh closure snapshot under the existing branch/reset lock."""
import sqlite3
from decimal import Decimal


def assert_close_permission(conn,actor_id,branch_id):
    owner=conn.execute('SELECT role,is_active FROM users WHERE id=? FOR UPDATE',(actor_id,)).fetchone()
    if not owner or not owner['is_active']:raise PermissionError('يلزم حساب نشط لإغلاق الوردية')
    if owner['role'] in ('Super_Admin','Admin','Manager','Supervisor','General_Supervisor','Branch_Supervisor'):return
    if not conn.execute("SELECT 1 FROM user_branch_permissions WHERE user_id=? AND branch_id=? AND permission_key='shift_close'",(actor_id,int(branch_id))).fetchone():raise PermissionError('لا يوجد تصريح إغلاق لهذه الوردية')


def prepare_close(conn,branch_id,shift_number,expected_rows,current_shift,actor_id):
    assert_close_permission(conn,actor_id,branch_id)
    raw=getattr(conn,'_conn',conn)
    if isinstance(raw,sqlite3.Connection):
        if not conn.in_transaction:conn.execute('BEGIN IMMEDIATE')
    else:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('branch-reset:'+str(int(branch_id)),))
    if int(current_shift(conn,int(branch_id)))!=int(shift_number):raise ValueError('تغيرت الوردية المفتوحة؛ حدّث التقرير قبل اعتماد الإغلاق')
    rows=conn.execute("SELECT id,total_amount,notes,payment_method,user_id FROM invoices WHERE branch_id=? AND shift_status=? ORDER BY id FOR UPDATE",(int(branch_id),str(int(shift_number)))).fetchall()
    def signature(values):return [(int(r['id']),Decimal(str(r['total_amount'] or 0)),str(r['notes'] or ''),str(r['payment_method'] or ''),r['user_id']) for r in values]
    if not rows or signature(rows)!=signature(expected_rows):raise ValueError('تغيرت فواتير الوردية أو قيمها؛ راجع الإجمالي الجديد قبل الإغلاق')
    return rows
