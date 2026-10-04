from ui_common import back_button
import streamlit as st
from database import get_db_connection


# ============================================================
# الصلاحيات
# ============================================================

def is_allowed(menu_name, role):

    if role in [
        "Admin",
        "General_Supervisor"
    ]:
        return True

    if role == "Cashier":
        return menu_name in [
            "🛒 نقطة البيع (POS)",
            "⭐ لوحة المفضلة (1-20)",
            "🔄 تزويد الفروع والأرشيف"
        ]

    if role == "Branch_Supervisor":
        return menu_name in [
            "🛒 نقطة البيع (POS)",
            "📦 إدارة المخزن والفروع",
            "🔄 تزويد الفروع والأرشيف"
        ]

    if role == "Viewer":
        return menu_name in [
            "📊 التقارير والأرباح"
        ]

    return False


# ============================================================
# الإحصائيات
# ============================================================

def get_dashboard_stats():

    conn = None

    try:

        conn = get_db_connection()

        role = st.session_state.get(
            "role",
            ""
        )

        branch_id = st.session_state.get(
            "branch_id"
        )

        # ----------------------------------------------------
        # Admin / General Supervisor
        # يشاهدان إجماليات النظام بالكامل
        # ----------------------------------------------------

        if role in [
            "Admin",
            "General_Supervisor"
        ]:

            sales = conn.execute(
                """
                SELECT COALESCE(
                    SUM(total_amount),
                    0
                )
                FROM invoices
                """
            ).fetchone()[0]

            branches = conn.execute(
                """
                SELECT COUNT(*)
                FROM branches
                """
            ).fetchone()[0]

            inventory = conn.execute(
                """
                SELECT COALESCE(
                    SUM(
                        quantity *
                        CASE
                            WHEN COALESCE(avg_cost, 0) > 0
                            THEN avg_cost
                            ELSE COALESCE(buy_price, 0)
                        END
                    ),
                    0
                )
                FROM items
                """
            ).fetchone()[0]

            users = conn.execute(
                """
                SELECT COUNT(*)
                FROM users
                """
            ).fetchone()[0]

        # ----------------------------------------------------
        # مستخدم مرتبط بفرع
        # ----------------------------------------------------

        elif branch_id is not None:

            sales = conn.execute(
                """
                SELECT COALESCE(
                    SUM(total_amount),
                    0
                )
                FROM invoices
                WHERE branch_id = ?
                """,
                (branch_id,)
            ).fetchone()[0]

            # المستخدم يرى فرعه فقط
            branches = 1

            inventory = conn.execute(
                """
                SELECT COALESCE(
                    SUM(
                        quantity *
                        CASE
                            WHEN COALESCE(avg_cost, 0) > 0
                            THEN avg_cost
                            ELSE COALESCE(buy_price, 0)
                        END
                    ),
                    0
                )
                FROM items
                WHERE branch_id = ?
                """,
                (branch_id,)
            ).fetchone()[0]

            users = conn.execute(
                """
                SELECT COUNT(*)
                FROM users
                WHERE branch_id = ?
                """,
                (branch_id,)
            ).fetchone()[0]

        # ----------------------------------------------------
        # مستخدم غير مربوط بفرع
        # ----------------------------------------------------

        else:

            sales = 0.0
            branches = 0
            inventory = 0.0
            users = 0

        return (
            float(sales or 0),
            int(branches or 0),
            float(inventory or 0),
            int(users or 0)
        )

    except Exception as e:

        st.error(
            "❌ تعذر تحميل إحصائيات لوحة التحكم."
        )

        st.code(str(e))

        return (
            0.0,
            0,
            0.0,
            0
        )

    finally:

        if conn:
            conn.close()


# ============================================================
# تنبيهات صلاحية دفعات المخزون
# ============================================================

def ensure_expiry_batches_table():
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_batches
            (
                id BIGSERIAL PRIMARY KEY,
                item_id INTEGER NOT NULL,
                branch_id INTEGER NOT NULL,
                quantity NUMERIC DEFAULT 0,
                remaining_quantity NUMERIC DEFAULT 0,
                received_date DATE DEFAULT CURRENT_DATE,
                expiry_date DATE,
                unit_cost NUMERIC DEFAULT 0,
                source_type TEXT DEFAULT 'inventory',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
                FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_inventory_batches_expiry
            ON inventory_batches(branch_id, expiry_date)
            """
        )
        conn.commit()
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def _table_columns(conn, table_name):
    """إرجاع أسماء أعمدة جدول SQLite بدون افتراض نسخة معينة من القاعدة."""
    try:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except Exception:
        return set()


def get_expiry_alerts():
    conn = None
    try:
        conn = get_db_connection()
        role = st.session_state.get("role", "")
        branch_id = st.session_state.get("branch_id")

        where_branch = ""
        params = []

        if role not in ["Admin", "General_Supervisor"]:
            if branch_id is None:
                return []
            where_branch = "AND b.branch_id = ?"
            params.append(branch_id)

        item_columns = _table_columns(conn, "items")
        no_expiry_filter = ""
        if "no_expiry" in item_columns:
            no_expiry_filter = "AND COALESCE(i.no_expiry, 0) = 0"

        # SQLite: julianday/date بدلاً من PostgreSQL INTERVAL وطرح التواريخ.
        return conn.execute(
            f"""
            SELECT
                b.id,
                i.item_code,
                i.item_name,
                br.branch_name,
                b.remaining_quantity,
                b.expiry_date,
                CAST(
                    julianday(date(b.expiry_date)) - julianday(date('now', 'localtime'))
                    AS INTEGER
                ) AS days_left
            FROM inventory_batches b
            JOIN items i ON i.id = b.item_id
            JOIN branches br ON br.id = b.branch_id
            WHERE b.expiry_date IS NOT NULL
              AND TRIM(CAST(b.expiry_date AS TEXT)) <> ''
              AND COALESCE(b.remaining_quantity, 0) > 0
              AND date(b.expiry_date) <= date('now', 'localtime', '+30 days')
              {no_expiry_filter}
              {where_branch}
            ORDER BY date(b.expiry_date) ASC, i.item_name ASC
            """,
            tuple(params)
        ).fetchall()
    finally:
        if conn:
            conn.close()


def get_low_stock_alerts(limit_value=5):
    """الأصناف التي أصبح إجمالي رصيدها في الفرع 5 كجم/قطع أو أقل، مع استبعاد الرصيد الصفري."""
    conn = None
    try:
        conn = get_db_connection()
        role = st.session_state.get("role", "")
        branch_id = st.session_state.get("branch_id")
        item_columns = _table_columns(conn, "items")

        unit_expr = "'piece'"
        if "unit_type" in item_columns:
            unit_expr = "COALESCE(i.unit_type, 'piece')"

        where_branch = ""
        params = []
        if role not in ["Admin", "General_Supervisor"]:
            if branch_id is None:
                return []
            where_branch = "AND b.branch_id = ?"
            params.append(branch_id)

        params.append(float(limit_value))

        return conn.execute(
            f"""
            SELECT
                i.id AS item_id,
                i.item_code,
                i.item_name,
                br.id AS branch_id,
                br.branch_name,
                {unit_expr} AS unit_type,
                COALESCE(SUM(b.remaining_quantity), 0) AS remaining_quantity
            FROM inventory_batches b
            JOIN items i ON i.id = b.item_id
            JOIN branches br ON br.id = b.branch_id
            WHERE 1=1
              {where_branch}
            GROUP BY i.id, i.item_code, i.item_name, br.id, br.branch_name, {unit_expr}
            HAVING COALESCE(SUM(b.remaining_quantity), 0) > 0
               AND COALESCE(SUM(b.remaining_quantity), 0) <= ?
            ORDER BY remaining_quantity ASC, i.item_name ASC
            """,
            tuple(params)
        ).fetchall()
    finally:
        if conn:
            conn.close()


def show_inventory_alerts():
    # التنبيهات الإدارية لا تظهر للكاشير.
    role = st.session_state.get("role", "")
    if role not in ["Admin", "General_Supervisor", "Branch_Supervisor"]:
        return

    try:
        ensure_expiry_batches_table()
        expiry_alerts = get_expiry_alerts()
        low_stock = get_low_stock_alerts(5)
    except Exception as e:
        st.error("❌ تعذر تحميل تنبيهات المخزون.")
        st.code(str(e))
        return

    expired = [r for r in expiry_alerts if int(r["days_left"] or 0) < 0]
    seven_days = [r for r in expiry_alerts if 0 <= int(r["days_left"] or 0) <= 7]
    thirty_days = [r for r in expiry_alerts if 8 <= int(r["days_left"] or 0) <= 30]

    st.markdown("### 🔔 تنبيهات المخزون")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 منتهي الصلاحية", len(expired))
    c2.metric("🟠 خلال 7 أيام", len(seven_days))
    c3.metric("🟡 خلال 30 يوماً", len(thirty_days))
    c4.metric("📉 رصيد 5 أو أقل", len(low_stock))

    if expired:
        st.error(f"🚨 يوجد {len(expired)} دفعة منتهية الصلاحية وبها رصيد متبقٍ.")
    if seven_days:
        st.warning(f"⚠️ يوجد {len(seven_days)} دفعة ستنتهي خلال 7 أيام.")
    if thirty_days:
        st.info(f"📅 يوجد {len(thirty_days)} دفعة ستنتهي خلال 30 يوماً.")
    if low_stock:
        st.warning(f"📉 يوجد {len(low_stock)} صنفاً وصل رصيده إلى 5 أو أقل.")

    if expiry_alerts:
        with st.expander("عرض تفاصيل تنبيهات الصلاحية", expanded=bool(expired)):
            for row in expiry_alerts:
                days = int(row["days_left"] or 0)
                if days < 0:
                    status = f"🔴 منتهي منذ {abs(days)} يوم"
                elif days == 0:
                    status = "🔴 ينتهي اليوم"
                elif days <= 7:
                    status = f"🟠 متبقي {days} يوم"
                else:
                    status = f"🟡 متبقي {days} يوم"

                st.write(
                    f"**{row['item_name']}** — {row['item_code']} | "
                    f"{row['branch_name']} | "
                    f"الرصيد بالدفعة: {float(row['remaining_quantity'] or 0):,.3f} | "
                    f"الانتهاء: {row['expiry_date']} | {status}"
                )

    if low_stock:
        with st.expander("عرض تفاصيل الأصناف منخفضة الرصيد", expanded=True):
            for row in low_stock:
                unit_type = str(row["unit_type"] or "").lower()
                unit_label = "كجم" if unit_type in ["kg", "kilo", "kilogram", "weight", "وزن", "كيلو"] else "قطعة"
                qty = float(row["remaining_quantity"] or 0)
                st.write(
                    f"📉 **{row['item_name']}** — {row['item_code']} | "
                    f"{row['branch_name']} | المتبقي: **{qty:,.3f} {unit_label}**"
                )


# إبقاء الاسم القديم للتوافق مع أي استدعاء آخر.
def show_expiry_alerts():
    show_inventory_alerts()


# ============================================================
# الصفحة
# ============================================================

def _dashboard_extra_stats():
    """ملخصات تشغيلية إضافية بدون تحويل لوحة الرئيسية إلى شاشة تنقل."""
    conn = get_db_connection()
    try:
        branch_id = st.session_state.get("branch_id")
        role = st.session_state.get("role", "")

        # المشتريات
        try:
            if role == "Admin" or not branch_id:
                row = conn.execute(
                    "SELECT COALESCE(SUM(total_amount), 0) AS total FROM purchases"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(total_amount), 0) AS total "
                    "FROM purchases WHERE branch_id = ?",
                    (branch_id,)
                ).fetchone()
            purchases_total = float(row["total"] or 0)
        except Exception:
            purchases_total = 0.0

        # التحويلات المعلقة
        try:
            if role == "Admin" or not branch_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM transfer_logs "
                    "WHERE COALESCE(status, '') NOT IN ('confirmed', 'completed', 'مؤكد', 'مكتمل')"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM transfer_logs "
                    "WHERE (from_branch_id = ? OR to_branch_id = ?) "
                    "AND COALESCE(status, '') NOT IN "
                    "('confirmed', 'completed', 'مؤكد', 'مكتمل')",
                    (branch_id, branch_id)
                ).fetchone()
            pending_transfers = int(row["cnt"] or 0)
        except Exception:
            pending_transfers = 0

        # أرصدة الموردين والعملاء
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(balance), 0) AS total FROM suppliers"
            ).fetchone()
            supplier_balance = float(row["total"] or 0)
        except Exception:
            supplier_balance = 0.0

        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(balance), 0) AS total FROM customers"
            ).fetchone()
            customer_balance = float(row["total"] or 0)
        except Exception:
            customer_balance = 0.0

        return purchases_total, pending_transfers, supplier_balance, customer_balance
    finally:
        conn.close()


def show_page():
    back_button(key="back_dashboard")

    st.markdown(
        """
        <h2 style="color:#0f172a;text-align:right;">
            🌟 مجموعة أبو زيد — لوحة المتابعة الرئيسية
        </h2>
        """,
        unsafe_allow_html=True
    )

    st.info(
        "هذه الصفحة للمتابعة والتنبيهات فقط. "
        "استخدم الأقسام الرئيسية في القائمة الجانبية للوصول إلى العمليات."
    )

    # تنبيهات الصلاحية
    show_expiry_alerts()
    st.markdown("---")

    # الإحصائيات الأساسية الموجودة بالنظام
    sales, branches, inventory, users = get_dashboard_stats()
    purchases_total, pending_transfers, supplier_balance, customer_balance = (
        _dashboard_extra_stats()
    )

    st.markdown("### 📌 ملخص التشغيل")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💰 إجمالي المبيعات", f"{sales:,.2f} د.ل")
    c2.metric("📥 إجمالي المشتريات", f"{purchases_total:,.2f} د.ل")
    c3.metric("📦 قيمة المخزون", f"{inventory:,.2f} د.ل")
    c4.metric("🔄 تحويلات معلقة", f"{pending_transfers}")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("🚛 أرصدة الموردين", f"{supplier_balance:,.2f} د.ل")
    c6.metric("🤝 أرصدة العملاء", f"{customer_balance:,.2f} د.ل")
    c7.metric("🏢 الفروع والمخازن", f"{branches}")
    c8.metric("👥 طاقم العمل", f"{users}")

    st.markdown("---")
    st.caption(
        "تم حذف شبكة اختصارات الشاشات والمفضلة من لوحة الرئيسية لمنع تكرار التنقل. "
        "الرئيسية الآن مخصصة للمؤشرات والتنبيهات فقط."
    )

