_PAGE_ERROR_UI_REVISION = 60
from views.page_guard import show_operation_error
from views.number_format import decimal_display
from views.ui_common import back_button
import streamlit as st
from database import get_db_connection


def _validated_role():
    """A Super_Admin claim requires the same current active account in the database."""
    role = st.session_state.get("role", "")
    if role not in ("Super_Admin","Manager"):
        return role
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT role, is_active FROM users WHERE id=?", (st.session_state.get("user_id"),)).fetchone()
    finally:
        conn.close()
    if not row or row["role"] != role or not row["is_active"]:
        st.error("تعذر اعتماد صلاحيات المستخدم الحالي؛ أعد تسجيل الدخول.")
        st.stop()
    return role

def format_money_ar(amount):
    """Display money as 6828,54 د.ل; no stored-data changes."""
    return f"{decimal_display(amount)} د.ل"


# ============================================================
# الصلاحيات
# ============================================================

def is_allowed(menu_name, role):
    if menu_name=='🛒 نقطة البيع (POS)':return True
    if role == "Super_Admin":
        role = _validated_role()

    if role in [
        "Super_Admin", "Admin", "Manager",
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

        role = _validated_role()

        branch_id = st.session_state.get(
            "branch_id"
        )

        # ----------------------------------------------------
        # Admin / General Supervisor
        # يشاهدان إجماليات النظام بالكامل
        # ----------------------------------------------------

        if role in [
            "Super_Admin", "Admin",
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

        show_operation_error(e, announce=False, context='views/dashboard.py:206')

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
    _validated_role()
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_batches
            (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        role = _validated_role()
        branch_id = st.session_state.get("branch_id")

        where_branch = ""
        params = []

        if role not in ["Super_Admin", "Admin", "Manager", "General_Supervisor"]:
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
        role = _validated_role()
        branch_id = st.session_state.get("branch_id")
        item_columns = _table_columns(conn, "items")

        unit_expr = "'piece'"
        if "unit_type" in item_columns:
            unit_expr = "COALESCE(i.unit_type, 'piece')"

        where_branch = ""
        params = []
        if role not in ["Super_Admin", "Admin", "Manager", "General_Supervisor"]:
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
    role = _validated_role()
    if role not in ["Super_Admin", "Admin", "Manager", "General_Supervisor", "Branch_Supervisor"]:
        return

    try:
        ensure_expiry_batches_table()
        expiry_alerts = get_expiry_alerts()
        low_stock = get_low_stock_alerts(5)
    except Exception as e:
        st.error("❌ تعذر تحميل تنبيهات المخزون.")
        show_operation_error(e, announce=False, context='views/dashboard.py:388')
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
                    f"الرصيد بالدفعة: {decimal_display(float(row['remaining_quantity'] or 0), 3)} | "
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
                    f"{row['branch_name']} | المتبقي: **{decimal_display(qty, 3)} {unit_label}**"
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
        role = _validated_role()

        # المشتريات
        try:
            if role in ("Super_Admin", "Admin", "Manager", "General_Supervisor") or not branch_id:
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
            if role in ("Super_Admin", "Admin", "Manager", "General_Supervisor") or not branch_id:
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


def _review_exception(invoice_id, item_id, decision):
    """Store a manager's review inside the invoice evidence, without changing stock."""
    _validated_role()
    role = str(_validated_role())
    if role not in {"Super_Admin", "Admin", "Manager", "Supervisor", "General_Supervisor", "Branch_Supervisor"}:
        raise PermissionError("لا توجد صلاحية لمراجعة البيع الاستثنائي")
    import json
    from datetime import datetime
    invoice_table='branch_exception_cache' if int(invoice_id)<0 else 'invoices'
    invoice_id=abs(int(invoice_id))
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id, branch_id, notes FROM "+invoice_table+" WHERE id=? FOR UPDATE", (invoice_id,)).fetchone()
        if not row:
            raise ValueError("الفاتورة غير موجودة")
        if role == "Branch_Supervisor" and str(row["branch_id"]) != str(st.session_state.get("branch_id")):
            raise PermissionError("هذه الفاتورة خارج فرعك")
        data = json.loads(row["notes"] or "{}")
        if not isinstance(data, dict):
            raise ValueError("تفاصيل الفاتورة غير صالحة")
        found = False
        for ex in data.get("stock_exceptions", []):
            if str(ex.get("item_id")) == str(item_id):
                if ex.get("review_status"):
                    raise ValueError("تمت مراجعة هذا البند بالفعل")
                ex["review_status"] = decision
                ex["reviewed_by"] = st.session_state.get("user_id")
                ex["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
                found = True
                break
        if not found:
            raise ValueError("بند البيع الاستثنائي غير موجود")
        conn.execute("UPDATE "+invoice_table+" SET notes=? WHERE id=?", (json.dumps(data, ensure_ascii=False), invoice_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def show_negative_sale_alerts():
    """Manager-only exceptional-sale review; surplus is adjusted separately."""
    role = str(_validated_role())
    if role not in {"Super_Admin", "Admin", "Manager", "Supervisor", "General_Supervisor", "Branch_Supervisor"}:
        return
    import json
    conn = None
    try:
        conn = get_db_connection()
        rows = conn.execute("""SELECT inv.id, inv.branch_id, inv.user_id, inv.notes,
                                     br.branch_name, u.username
                              FROM invoices inv
                              LEFT JOIN branches br ON br.id=inv.branch_id
                              LEFT JOIN users u ON u.id=inv.user_id
                              ORDER BY inv.id DESC LIMIT 500""").fetchall()
        # A separate evidence cache cannot contribute to sales, revenue or shift totals.
        cached=conn.execute("""SELECT -c.id AS id,c.branch_id,c.user_id,c.notes,c.branch_name,c.username
            FROM branch_exception_cache c JOIN branch_settlement_authorities a ON a.branch_id=c.branch_id
            AND a.authority_uuid=c.authority_uuid AND a.is_released=0
            WHERE NOT EXISTS(SELECT 1 FROM invoices i WHERE i.offline_uuid=c.offline_uuid)""").fetchall()
        rows=list(rows)+list(cached)
        alerts = []
        for row in rows:
            if role == "Branch_Supervisor" and str(row["branch_id"]) != str(st.session_state.get("branch_id")):
                continue
            try:
                details = json.loads(row["notes"] or "{}")
                if not isinstance(details, dict):
                    continue
                for ex in details.get("stock_exceptions", []):
                    alerts.append({
                        "invoice_id": row["id"], "item_id": ex.get("item_id"), "invoice_display": details.get("_invoice_number") or row["id"],
                        "الفرع": row["branch_name"] or row["branch_id"],
                        "الكاشير": row["username"] or row["user_id"],
                        "الصنف": ex.get("item_name", ""),
                        "الكمية المباعة": ex.get("requested_qty", 0),
                        "الرصيد المتاح": ex.get("available_qty", 0),
                        "العجز": ex.get("shortfall_qty", 0),
                        "الوقت": ex.get("recorded_at", ""),
                        "الحالة": ex.get("review_status") or "بانتظار المراجعة",
                        "المراجع": ex.get("reviewed_by") or "",
                        "وقت المراجعة": ex.get("reviewed_at") or "",
                        "تمت تسوية الفائض": bool(ex.get("surplus_adjustment_done")),
                        "كمية الفائض المعتمدة": ex.get("surplus_adjustment_qty") or 0,
                        "العجز المتبقي": ex.get("surplus_remaining_qty", ex.get("shortfall_qty",0)),
                        "branch_id": row["branch_id"],
                    })
            except (ValueError, TypeError, AttributeError):
                continue
        pending = [x for x in alerts if x["الحالة"] == "بانتظار المراجعة"]
        if pending:
            st.warning(f"🚨 بيع استثنائي: {len(pending)} بند بانتظار مراجعة الإدارة")
            latest = tuple(sorted((str(x["invoice_id"]), str(x["item_id"])) for x in pending))
            if st.session_state.get("_exception_alert_seen") != latest:
                st.session_state["_exception_alert_seen"] = latest
                @st.dialog("🚨 تنبيه إداري — بيع استثنائي")
                def _exception_popup():
                    st.warning(f"يوجد {len(pending)} بند بيع استثنائي يحتاج مراجعة.")
                    for entry in pending[:5]:
                        st.write(f"فاتورة {entry['invoice_id']} | {entry['الفرع']} | {entry['الصنف']} | عجز {entry['العجز']}")
                    if st.button("اطلعت على التنبيه", key="exception_popup_ok"):
                        st.rerun()
                _exception_popup()
        if alerts:
            with st.expander("🔔 سجل البيع الاستثنائي — للإدارة فقط", expanded=bool(pending)):
                st.dataframe([{
                    "رقم الفاتورة": x.get("invoice_display",x["invoice_id"]),
                    **{k: v for k, v in x.items() if k not in {"invoice_id", "item_id", "branch_id", "invoice_display"}}
                } for x in alerts], use_container_width=True, hide_index=True)
                st.caption("مراجعة البيع لا تعدّل المخزون. أضف الفائض بعد الجرد من شاشة تسويات المخزون وبالصلاحيات الحالية.")
                if pending:
                    choices = {f"فاتورة {x.get('invoice_display',x['invoice_id'])} — {x['الصنف']} — {x['الفرع']} ({i+1})": x for i,x in enumerate(pending)}
                    chosen = st.selectbox("اختر بند البيع الاستثنائي للمراجعة", list(choices), key="exception_review_choice")
                    selected = choices[chosen]
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ تمت المراجعة", key="exception_review_confirm"):
                            try:
                                _review_exception(selected["invoice_id"], selected["item_id"], "تمت المراجعة")
                                st.rerun()
                            except Exception as e:
                                show_operation_error(e, announce=True, context='views/dashboard.py:638')
                    with c2:
                        if st.button("⚠️ يحتاج تحقيق", key="exception_review_investigate"):
                            try:
                                _review_exception(selected["invoice_id"], selected["item_id"], "يحتاج تحقيق")
                                st.rerun()
                            except Exception as e:
                                show_operation_error(e, announce=True, context='views/dashboard.py:645')
                # إضافة الفائض اختيارية بعد الجرد، وبنفس تأكيد كلمة المرور الأصلي.
                if role in {"Super_Admin", "Admin", "Manager", "General_Supervisor"}:
                    available = [x for x in alerts if not x["تمت تسوية الفائض"]]
                    if available:
                        st.markdown("#### ربط تسوية الفائض بالبيع الاستثنائي")
                        refs = {f"فاتورة {x.get('invoice_display',x['invoice_id'])} — {x['الصنف']} — {x['الفرع']} ({i+1})": x
                                for i, x in enumerate(available)}
                        ref = refs[st.selectbox("اختر عملية البيع", list(refs), key="linked_surplus_invoice")]
                        amount = st.number_input("الفائض الفعلي بعد الجرد (كجم)", min_value=0.01,
                                                 value=0.5, step=0.25, format="%.2f", key="linked_surplus_amount")
                        st.caption("الكمية المدخلة هي الفائض الفعلي المعتمد، وليست العجز المحسوب تلقائيًا.")
                        if st.button("اعتماد تسوية الفائض المرتبطة", key="linked_surplus_confirm"):
                            from views.adjustments import secure_action_dialog, execute_add_surplus
                            secure_action_dialog(
                                f"تسوية فائض بيع استثنائي لفاتورة {ref.get('invoice_display',ref['invoice_id'])}",
                                execute_add_surplus, ref["branch_id"], ref["item_id"], amount, ref["invoice_id"], __import__("uuid").uuid4().hex
                            )
    except Exception:
        st.warning("تعذر تحميل سجل البيع الاستثنائي حالياً.")
    finally:
        if conn is not None:
            conn.close()


def show_page():
    back_button(key="back_dashboard")
    show_dashboard(st.session_state.get("username", ""), _validated_role(), st.session_state.get("branch_id"))
    show_negative_sale_alerts()



# ===== لوحة Contabo التفصيلية بنسخة محلية تعمل دون إنترنت =====
import html

def _num(value):
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def _format_number(value):
    return f"{_num(value):.3f}".rstrip("0").rstrip(".")


def _money(value):
    return f"{_format_number(value)} د.ل"


def _query(conn, sql):
    cur = conn.execute(sql)
    try:
        return cur.fetchall()
    finally:
        try:
            cur.close()
        except Exception:
            pass


def show_dashboard(username, role, branch_id=None):
    role = _validated_role()
    from central_inventory import show_central_inventory
    show_central_inventory(role)
    from views.update_distribution import render_installation_dashboard
    render_installation_dashboard()
