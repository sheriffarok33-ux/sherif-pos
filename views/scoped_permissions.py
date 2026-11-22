"""Branch-scoped additive permissions; default-deny for exceptions."""

def ensure_scoped_permissions(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS user_branch_permissions (
        user_id INTEGER NOT NULL, branch_id INTEGER NOT NULL,
        permission_key TEXT NOT NULL, granted_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id, branch_id, permission_key))""")

def has_scoped_permission(conn, user_id, branch_id, permission_key):
    if user_id is None or branch_id is None:
        return False
    ensure_scoped_permissions(conn)
    return conn.execute("""SELECT 1 FROM user_branch_permissions
        WHERE user_id=? AND branch_id=? AND permission_key=? LIMIT 1""",
        (user_id, branch_id, permission_key)).fetchone() is not None


# Permission registry shared by the user-management screen and operational views.
# Grants are additive; existing role permissions remain unchanged.
PERMISSION_GROUPS = {
    "الورديات ونقطة البيع": {
        "السماح بالبيع من شاشة نقاط البيع (POS)": "pos_sell",
        "عرض تقرير الوردية": "shift_view",
        "إغلاق وردية الفرع": "shift_close",
    },
    "التقارير والخزينة": {
        "عرض الملخص المالي للفرع": "treasury_report_view",
        "عرض تقارير المبيعات": "sales_report_view",
    },
    "المخزون": {
        "عرض المخزون": "inventory_view",
        "إدارة أصناف المخزون": "inventory_manage",
        "اعتماد تحويل مخزون": "stock_transfer_approve",
        "تسجيل الهالك والمرتجعات": "stock_adjustment_manage",
    },
    "المشتريات": {
        "عرض المشتريات": "purchases_view",
        "تسجيل مشتريات": "purchases_manage",
    },
    "المالية": {
        "عرض المصروفات": "expenses_view",
        "تسجيل مصروفات وإيرادات": "expenses_manage",
    },
}


def scoped_branch_ids(conn, user_id, permission_key):
    """Return explicitly granted branch IDs; no global implicit access."""
    if user_id is None:
        return set()
    ensure_scoped_permissions(conn)
    return {int(row[0]) for row in conn.execute(
        "SELECT branch_id FROM user_branch_permissions WHERE user_id=? AND permission_key=?",
        (user_id, permission_key)
    ).fetchall()}
