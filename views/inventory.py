from views.ui_common import back_button
from views.ui_common import item_alerts
import streamlit as st
import pandas as pd
import io
from datetime import date
from database import get_db_connection


def ensure_inventory_columns():
    conn = None
    try:
        conn = get_db_connection()
        # SQLite does not support PostgreSQL's ADD COLUMN IF NOT EXISTS syntax.
        # Check the existing columns first, then add only the missing ones.
        existing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(items)").fetchall()
        }
        if "unit_type" not in existing_columns:
            conn.execute("ALTER TABLE items ADD COLUMN unit_type TEXT DEFAULT 'piece'")
        if "pieces_per_carton" not in existing_columns:
            conn.execute("ALTER TABLE items ADD COLUMN pieces_per_carton INTEGER DEFAULT 1")
        conn.execute(
            """
            UPDATE items
            SET unit_type = 'piece'
            WHERE unit_type IS NULL OR TRIM(unit_type) = ''
            """
        )
        conn.execute(
            """
            UPDATE items
            SET pieces_per_carton = 1
            WHERE pieces_per_carton IS NULL OR pieces_per_carton < 1
            """
        )
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


def get_branches():
    conn = None
    try:
        conn = get_db_connection()
        return conn.execute(
            "SELECT id, branch_name FROM branches ORDER BY id ASC"
        ).fetchall()
    finally:
        if conn:
            conn.close()


def get_branch_items_rows(branch_id):
    conn = None
    try:
        conn = get_db_connection()
        return conn.execute(
            """
            SELECT id, item_code, item_name, quantity, buy_price,
                   avg_cost, sale_price,
                   COALESCE(unit_type, 'piece') AS unit_type,
                   COALESCE(pieces_per_carton, 1) AS pieces_per_carton
            FROM items
            WHERE branch_id = ?
            ORDER BY item_name ASC, item_code ASC
            """,
            (branch_id,)
        ).fetchall()
    finally:
        if conn:
            conn.close()


def get_branch_items(branch_id):
    conn = None
    try:
        conn = get_db_connection()
        rows = conn.execute(
            """
            SELECT
                i.id,
                i.item_code,
                i.item_name,
                i.quantity,
                i.buy_price,
                i.avg_cost,
                i.sale_price,
                COALESCE(i.unit_type, 'piece') AS unit_type,
                COALESCE(i.pieces_per_carton, 1) AS pieces_per_carton,
                MIN(
                    CASE
                        WHEN b.expiry_date IS NOT NULL
                         AND COALESCE(b.remaining_quantity, 0) > 0
                        THEN b.expiry_date
                    END
                ) AS nearest_expiry
            FROM items i
            LEFT JOIN inventory_batches b
              ON b.item_id = i.id
             AND b.branch_id = i.branch_id
            WHERE i.branch_id = ?
            GROUP BY
                i.id, i.item_code, i.item_name, i.quantity,
                i.buy_price, i.avg_cost, i.sale_price,
                i.unit_type, i.pieces_per_carton
            ORDER BY i.item_name ASC, i.item_code ASC
            """,
            (branch_id,)
        ).fetchall()

        data = []
        today = date.today()

        for row in rows:
            unit_type = row["unit_type"] or "piece"
            nearest = row["nearest_expiry"]

            if nearest:
                days_left = (nearest - today).days
                if days_left < 0:
                    expiry_text = f"🔴 {nearest} (منتهي)"
                elif days_left == 0:
                    expiry_text = f"🔴 {nearest} (اليوم)"
                elif days_left <= 7:
                    expiry_text = f"🟠 {nearest} ({days_left} يوم)"
                elif days_left <= 30:
                    expiry_text = f"🟡 {nearest} ({days_left} يوم)"
                else:
                    expiry_text = f"🟢 {nearest}"
            else:
                expiry_text = "—"

            data.append({
                "الكود": row["item_code"],
                "اسم الصنف": row["item_name"],
                "الوحدة": "كجم" if unit_type == "kg" else "قطعة",
                "الرصيد": float(row["quantity"] or 0),
                "أقرب تاريخ انتهاء": expiry_text,
                "آخر تكلفة للوحدة": float(row["buy_price"] or 0),
                "متوسط تكلفة الوحدة": float(row["avg_cost"] or 0),
                "سعر بيع الوحدة": float(row["sale_price"] or 0),
            })

        return pd.DataFrame(data)
    finally:
        if conn:
            conn.close()


def add_stock_to_existing_item(
    branch_id, item_id, added_quantity, unit_buy_price, unit_type,
    pieces_per_carton=None, expiry_date=None
):
    conn = None
    try:
        added_quantity = float(added_quantity)
        unit_buy_price = float(unit_buy_price)

        if added_quantity <= 0:
            raise ValueError("الكمية المضافة يجب أن تكون أكبر من صفر.")
        if unit_buy_price < 0:
            raise ValueError("سعر الشراء لا يمكن أن يكون سالباً.")

        conn = get_db_connection()
        existing = conn.execute(
            """
            SELECT id, item_name, quantity, buy_price, avg_cost,
                   COALESCE(unit_type, 'piece') AS unit_type,
                   COALESCE(pieces_per_carton, 1) AS pieces_per_carton
            FROM items
            WHERE id = ? AND branch_id = ?
            FOR UPDATE
            """,
            (item_id, branch_id)
        ).fetchone()

        if not existing:
            raise ValueError("الصنف المحدد غير موجود في هذا الفرع.")

        stored_type = existing["unit_type"] or "piece"
        if stored_type != unit_type:
            raise ValueError("وحدة الإضافة لا تطابق وحدة الصنف المسجلة.")

        old_qty = float(existing["quantity"] or 0)
        old_avg = float(existing["avg_cost"] or 0)
        old_buy = float(existing["buy_price"] or 0)
        if old_avg <= 0:
            old_avg = old_buy

        new_qty = old_qty + added_quantity
        new_avg = (
            ((old_qty * old_avg) + (added_quantity * unit_buy_price)) / new_qty
            if new_qty > 0 else unit_buy_price
        )

        conn.execute(
            """
            UPDATE items
            SET quantity = ?, buy_price = ?, avg_cost = ?,
                pieces_per_carton = 1
            WHERE id = ? AND branch_id = ?
            """,
            (new_qty, unit_buy_price, new_avg, item_id, branch_id)
        )

        if expiry_date:
            conn.execute(
                """
                INSERT INTO inventory_batches
                (
                    item_id, branch_id, quantity, remaining_quantity,
                    expiry_date, unit_cost, source_type
                )
                VALUES (?, ?, ?, ?, ?, ?, 'inventory')
                """,
                (
                    item_id, branch_id, added_quantity, added_quantity,
                    expiry_date, unit_buy_price
                )
            )

        conn.commit()
        label = "كجم" if stored_type == "kg" else "قطعة"
        _inventory_done(
            f"تمت إضافة {added_quantity:,.3f} {label} إلى "
            f"({existing['item_name']}). الرصيد الجديد: {new_qty:,.3f} {label}."
        )
    except Exception as e:
        if conn:
            conn.rollback()
        st.error("❌ تعذر إضافة الكمية للصنف.")
        st.code(str(e))
    finally:
        if conn:
            conn.close()


def create_new_inventory_item(
    branch_id, item_code, item_name, initial_quantity,
    unit_buy_price, sale_price, unit_type, pieces_per_carton,
    expiry_date=None
):
    conn = None
    try:
        item_code = item_code.strip()
        item_name = item_name.strip()
        if not item_code:
            raise ValueError("يجب إدخال كود الصنف / الباركود.")
        if not item_name:
            raise ValueError("يجب إدخال اسم الصنف.")

        initial_quantity = float(initial_quantity)
        unit_buy_price = float(unit_buy_price)
        sale_price = float(sale_price)

        if initial_quantity <= 0:
            raise ValueError("الكمية الأولية يجب أن تكون أكبر من صفر.")
        if unit_buy_price < 0 or sale_price < 0:
            raise ValueError("الأسعار لا يمكن أن تكون سالبة.")

        conn = get_db_connection()
        duplicate = conn.execute(
            """
            SELECT id
            FROM items
            WHERE branch_id = ?
              AND (
                    item_code = ?
                    OR LOWER(TRIM(item_name)) = LOWER(TRIM(?))
                  )
            LIMIT 1
            """,
            (branch_id, item_code, item_name)
        ).fetchone()

        if duplicate:
            raise ValueError(
                "هذا الصنف موجود بالفعل في الفرع. "
                "استخدم «إضافة كمية لصنف موجود»."
            )

        inserted = conn.execute(
            """
            INSERT INTO items
            (
                item_code, item_name, branch_id, quantity,
                buy_price, sale_price, avg_cost,
                unit_type, pieces_per_carton
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                item_code, item_name, branch_id, initial_quantity,
                unit_buy_price, sale_price, unit_buy_price,
                unit_type, 1
            )
        ).fetchone()

        new_item_id = inserted[0]

        if expiry_date:
            conn.execute(
                """
                INSERT INTO inventory_batches
                (
                    item_id, branch_id, quantity, remaining_quantity,
                    expiry_date, unit_cost, source_type
                )
                VALUES (?, ?, ?, ?, ?, ?, 'inventory')
                """,
                (
                    new_item_id, branch_id, initial_quantity,
                    initial_quantity, expiry_date, unit_buy_price
                )
            )

        conn.commit()

        label = "كجم" if unit_type == "kg" else "قطعة"
        _inventory_done(
            f"تم إنشاء الصنف ({item_name}) برصيد أولي {initial_quantity:,.3f} {label}."
        )
    except Exception as e:
        if conn:
            conn.rollback()
        st.error("❌ تعذر إنشاء الصنف الجديد.")
        st.code(str(e))
    finally:
        if conn:
            conn.close()


def piece_input_fields(prefix, default_pieces=1):
    c1, c2 = st.columns(2)
    qty = c1.number_input(
        "الكمية بالقطعة:",
        min_value=1.0,
        value=1.0,
        step=1.0,
        format="%.0f",
        key=f"{prefix}_piece_qty"
    )
    unit_cost = c2.number_input(
        "سعر شراء القطعة:",
        min_value=0.0,
        value=0.0,
        step=0.5,
        format="%.2f",
        key=f"{prefix}_piece_cost"
    )
    return float(qty), float(unit_cost), 1

def change_legacy_unit(item_id, branch_id, new_type, pieces_per_carton=1):
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            """
            UPDATE items
            SET unit_type = ?, pieces_per_carton = ?
            WHERE id = ? AND branch_id = ?
            """,
            (new_type, int(pieces_per_carton or 1), item_id, branch_id)
        )
        conn.commit()
        _inventory_done("تم تحديث وحدة الصنف بنجاح.")
    except Exception as e:
        if conn:
            conn.rollback()
        st.error("تعذر تحديث وحدة الصنف.")
        st.code(str(e))
    finally:
        if conn:
            conn.close()



def _set_inventory_mode(mode):
    st.session_state["inventory_mode"] = mode
    st.rerun()


def _excel_bytes(df, sheet_name="Inventory"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return output.getvalue()


def _update_items_from_editor(branch_id, original_rows, edited_df):
    """يحفظ تعديلات جدول الأصناف، ويسجل أي تغيير مباشر في الكمية."""
    conn = None
    try:
        original = {int(r["id"]): r for r in original_rows}
        conn = get_db_connection()

        for _, row in edited_df.iterrows():
            item_id = int(row["id"])
            old = original.get(item_id)
            if not old:
                continue

            item_code = str(row["كود الصنف"] or "").strip()
            item_name = str(row["اسم الصنف"] or "").strip()
            unit_ar = str(row["الوحدة"] or "قطعة").strip()
            unit_type = "kg" if unit_ar == "كجم" else "piece"
            ppc = 1
            new_qty = float(row["الكمية"] or 0)
            buy_price = float(row["سعر الشراء"] or 0)
            avg_cost = float(row["متوسط التكلفة"] or 0)
            sale_price = float(row["سعر البيع"] or 0)

            if not item_code or not item_name:
                raise ValueError("كود الصنف واسم الصنف لا يمكن أن يكونا فارغين.")
            if new_qty < 0 or buy_price < 0 or avg_cost < 0 or sale_price < 0:
                raise ValueError(f"لا يمكن إدخال قيمة سالبة للصنف: {item_name}")

            duplicate = conn.execute(
                """
                SELECT id FROM items
                WHERE branch_id = ?
                  AND id <> ?
                  AND (
                        item_code = ?
                        OR LOWER(TRIM(item_name)) = LOWER(TRIM(?))
                      )
                LIMIT 1
                """,
                (branch_id, item_id, item_code, item_name)
            ).fetchone()
            if duplicate:
                raise ValueError(
                    f"يوجد صنف آخر بنفس الكود أو الاسم: {item_name} / {item_code}"
                )

            old_qty = float(old["quantity"] or 0)
            delta = new_qty - old_qty

            conn.execute(
                """
                UPDATE items
                SET item_code = ?,
                    item_name = ?,
                    quantity = ?,
                    buy_price = ?,
                    avg_cost = ?,
                    sale_price = ?,
                    unit_type = ?,
                    pieces_per_carton = ?
                WHERE id = ? AND branch_id = ?
                """,
                (
                    item_code, item_name, new_qty, buy_price, avg_cost,
                    sale_price, unit_type, ppc, item_id, branch_id
                )
            )

            if abs(delta) > 1e-9:
                conn.execute(
                    """
                    INSERT INTO stock_adjustments
                    (
                        branch_id, item_id, item_name, quantity,
                        adjustment_type, loss_or_gain_value, notes
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        branch_id, item_id, item_name, abs(delta),
                        "تعديل يدوي للكمية - زيادة" if delta > 0
                        else "تعديل يدوي للكمية - نقص",
                        (-abs(delta) * avg_cost) if delta < 0 else 0.0,
                        "تعديل مباشر من شاشة الأصناف"
                    )
                )

        conn.commit()
        _inventory_done("تم حفظ تعديلات الأصناف بنجاح.")
    except Exception as e:
        if conn:
            conn.rollback()
        st.error("❌ تعذر حفظ تعديلات الأصناف.")
        st.code(str(e))
    finally:
        if conn:
            conn.close()


def _delete_inventory_item(branch_id, item_id):
    conn = None
    try:
        conn = get_db_connection()
        row = conn.execute(
            """
            SELECT item_name, quantity, COALESCE(avg_cost, buy_price, 0) AS cost
            FROM items
            WHERE id = ? AND branch_id = ?
            FOR UPDATE
            """,
            (item_id, branch_id)
        ).fetchone()
        if not row:
            raise ValueError("الصنف غير موجود.")

        qty = float(row["quantity"] or 0)
        cost = float(row["cost"] or 0)
        if qty > 0:
            conn.execute(
                """
                INSERT INTO stock_adjustments
                (
                    branch_id, item_id, item_name, quantity,
                    adjustment_type, loss_or_gain_value, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    branch_id, item_id, row["item_name"], qty,
                    "حذف صنف من المخزون", -(qty * cost),
                    "حذف يدوي من شاشة الأصناف"
                )
            )

        # inventory_batches تحذف تلقائياً بسبب ON DELETE CASCADE.
        conn.execute(
            "DELETE FROM items WHERE id = ? AND branch_id = ?",
            (item_id, branch_id)
        )
        conn.commit()
        _inventory_done("تم حذف الصنف بنجاح.")
    except Exception as e:
        if conn:
            conn.rollback()
        st.error("❌ تعذر حذف الصنف.")
        st.code(str(e))
    finally:
        if conn:
            conn.close()


def _editable_inventory_dataframe(rows):
    data = []
    for row in rows:
        data.append({
            "id": int(row["id"]),
            "كود الصنف": row["item_code"] or "",
            "اسم الصنف": row["item_name"] or "",
            "الوحدة": "كجم" if (row["unit_type"] or "piece") == "kg" else "قطعة",
            "الكمية": float(row["quantity"] or 0),
            "سعر الشراء": float(row["buy_price"] or 0),
            "متوسط التكلفة": float(row["avg_cost"] or 0),
            "سعر البيع": float(row["sale_price"] or 0),
        })
    return pd.DataFrame(data)


@st.dialog("✅ تمت العملية بنجاح")
def _inventory_success_dialog():
    st.success(st.session_state.get("inventory_success_message", "تمت العملية بنجاح."))
    if st.button("موافق", type="primary", use_container_width=True, key="inventory_success_ok"):
        st.session_state.pop("inventory_success_pending", None)
        st.session_state.pop("inventory_success_message", None)
        st.rerun()


def _inventory_done(message):
    st.session_state["inventory_success_message"] = message
    st.session_state["inventory_success_pending"] = True
    st.rerun()



@st.dialog("⚠️ مراجعة العملية قبل التنفيذ")
def _inventory_confirm_confirm_dialog():
    pending = st.session_state.get("inventory_confirm_pending_action")
    if not pending:
        return
    st.warning("راجع البيانات جيدًا. لن يتم تنفيذ أي تغيير قبل التأكيد.")
    for label, value in pending.get("summary", []):
        st.write(f"**{label}:** {value}")
    c1, c2 = st.columns(2)
    if c1.button("✅ تأكيد التنفيذ", type="primary", use_container_width=True, key="inventory_confirm_confirm_yes"):
        callback = pending.get("callback")
        args = pending.get("args", [])
        kwargs = pending.get("kwargs", {})
        st.session_state.pop("inventory_confirm_pending_action", None)
        callback(*args, **kwargs)
    if c2.button("❌ إلغاء", use_container_width=True, key="inventory_confirm_confirm_no"):
        st.session_state.pop("inventory_confirm_pending_action", None)
        st.rerun()


def show_page():
    back_button(key="back_inventory")
    item_alerts(st.session_state.get("branch_id"), key="alerts_inventory")

    if st.session_state.get("inventory_confirm_pending_action"):
        _inventory_confirm_confirm_dialog()
        st.stop()

    if st.session_state.get("inventory_success_pending"):
        _inventory_success_dialog()

    try:
        ensure_inventory_columns()
    except Exception as e:
        st.error("❌ تعذر تجهيز حقول وحدات المخزون.")
        st.code(str(e))
        return

    st.markdown("## 📦 المخزون والأصناف")
    st.caption(
        "إدارة الأصناف بنظام قطعة أو كجم فقط، مع الكمية وسعر الشراء وسعر البيع والصلاحية. "
        "يمكن النسخ واللصق والتعديل داخل جدول الأصناف ثم الضغط على حفظ."
    )

    try:
        branches = get_branches()
    except Exception as e:
        st.error("❌ تعذر تحميل الفروع.")
        st.code(str(e))
        return

    if not branches:
        st.warning("⚠️ يرجى إنشاء مخزن أو فرع أولاً.")
        return

    b_dict = {b["branch_name"]: b["id"] for b in branches}
    selected_branch = st.selectbox(
        "🏢 اختر المخزن أو الفرع:",
        list(b_dict.keys()),
        key="inventory_branch"
    )
    branch_id = b_dict[selected_branch]

    try:
        existing_items = get_branch_items_rows(branch_id)
    except Exception as e:
        st.error("❌ تعذر تحميل أصناف الفرع.")
        st.code(str(e))
        existing_items = []

    if "inventory_mode" not in st.session_state:
        st.session_state["inventory_mode"] = "list"

    if not st.session_state.get("inventory_entry_lock"):
        mode_labels = {
            "📋 الأصناف والتعديل": "list",
            "📦 إضافة كمية": "add",
            "➕ صنف جديد": "new",
            "📅 الصلاحيات": "expiry",
        }
        current_label = next((k for k,v in mode_labels.items() if v == st.session_state["inventory_mode"]), list(mode_labels)[0])
        selected_label = st.selectbox("اختر العملية:", list(mode_labels), index=list(mode_labels).index(current_label), key="inventory_action_dropdown")
        selected_mode = mode_labels[selected_label]
        if selected_mode != st.session_state["inventory_mode"]:
            st.session_state["inventory_mode"] = selected_mode
            st.rerun()
    
    mode = st.session_state["inventory_mode"]
    st.markdown("---")

    # =========================================================
    # جدول الأصناف + تعديل + حذف + نسخ + Excel
    # =========================================================
    if mode == "list":
        st.markdown("### 📋 الأصناف والتعديل المباشر")
        if not existing_items:
            st.info("لا توجد أصناف في هذا الفرع حتى الآن.")
            return

        original_df = _editable_inventory_dataframe(existing_items)

        st.info(
            "💡 يمكنك تحديد الخلايا ثم النسخ واللصق مباشرة داخل الجدول. "
            "اضغط Enter بعد تحرير الخلية، ثم اضغط «حفظ كل التعديلات»."
        )

        edited_df = st.data_editor(
            original_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key=f"inventory_editor_{branch_id}",
            disabled=["id"],
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "الوحدة": st.column_config.SelectboxColumn(
                    "الوحدة", options=["قطعة", "كجم"], required=True
                ),
                "الكمية": st.column_config.NumberColumn(
                    "الكمية", min_value=0.0, format="%.3f"
                ),
                "سعر الشراء": st.column_config.NumberColumn(
                    "سعر الشراء", min_value=0.0, format="%.2f"
                ),
                "متوسط التكلفة": st.column_config.NumberColumn(
                    "متوسط التكلفة", min_value=0.0, format="%.2f"
                ),
                "سعر البيع": st.column_config.NumberColumn(
                    "سعر البيع", min_value=0.0, format="%.2f"
                ),
            }
        )

        a1, a2, a3 = st.columns(3)
        if a1.button(
            "💾 حفظ كل التعديلات",
            type="primary",
            use_container_width=True
        ):
            _update_items_from_editor(branch_id, existing_items, edited_df)

        a2.download_button(
            "📥 تصدير الأصناف إلى Excel",
            data=_excel_bytes(edited_df.drop(columns=["id"]), "Items"),
            file_name=f"inventory_{branch_id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

        item_map = {
            f"[{r['item_code']}] {r['item_name']}": r
            for r in existing_items
        }
        selected_label = st.selectbox(
            "اختر صنفًا لعمليات النسخ أو الحذف:",
            list(item_map.keys()),
            key=f"inventory_manage_item_{branch_id}"
        )
        selected = item_map[selected_label]

        b1, b2 = st.columns(2)
        if b1.button("📋 تجهيز بيانات الصنف للنسخ", use_container_width=True):
            st.session_state["inventory_copy_text"] = (
                f"{selected['item_code']}\t{selected['item_name']}\t"
                f"{selected['quantity']}\t{selected['buy_price']}\t"
                f"{selected['avg_cost']}\t{selected['sale_price']}"
            )

        if st.session_state.get("inventory_copy_text"):
            st.code(
                st.session_state["inventory_copy_text"],
                language=None
            )

        if b2.button(
            "🗑️ حذف الصنف المختار",
            use_container_width=True
        ):
            st.session_state["inventory_delete_id"] = int(selected["id"])

        if st.session_state.get("inventory_delete_id") == int(selected["id"]):
            st.warning(
                f"⚠️ سيتم حذف الصنف «{selected['item_name']}» من هذا الفرع. "
                "دفعات الصلاحية المرتبطة به ستحذف أيضًا."
            )
            d1, d2 = st.columns(2)
            if d1.button(
                "✅ تأكيد الحذف",
                type="primary",
                use_container_width=True,
                key=f"confirm_delete_item_{selected['id']}"
            ):
                _delete_inventory_item(branch_id, int(selected["id"]))
            if d2.button(
                "↩️ إلغاء",
                use_container_width=True,
                key=f"cancel_delete_item_{selected['id']}"
            ):
                st.session_state.pop("inventory_delete_id", None)
                st.rerun()

    # =========================================================
    # إضافة كمية
    # =========================================================
    elif mode == "add":
        st.markdown("### 📦 إضافة كمية لصنف موجود")
        if not existing_items:
            st.info("لا توجد أصناف في هذا الفرع حتى الآن.")
            return

        item_map = {}
        for item in existing_items:
            unit = "كجم" if item["unit_type"] == "kg" else "قطعة"
            label = (
                f"{item['item_name']} — {item['item_code']} — "
                f"الرصيد: {float(item['quantity'] or 0):,.3f} {unit}"
            )
            item_map[label] = item

        selected = item_map[
            st.selectbox(
                "اختر الصنف:",
                list(item_map.keys()),
                key="inventory_add_item"
            )
        ]
        unit_type = selected["unit_type"] or "piece"
        unit_label = "كجم" if unit_type == "kg" else "قطعة"

        m1, m2, m3 = st.columns(3)
        m1.metric("الرصيد الحالي", f"{float(selected['quantity'] or 0):,.3f} {unit_label}")
        m2.metric("متوسط التكلفة", f"{float(selected['avg_cost'] or 0):,.2f} د.ل/{unit_label}")
        m3.metric("سعر البيع", f"{float(selected['sale_price'] or 0):,.2f} د.ل/{unit_label}")

        if unit_type == "piece":
            added_qty, unit_cost, ppc = piece_input_fields(
                "existing_btn", selected["pieces_per_carton"]
            )
        else:
            q1, q2 = st.columns(2)
            added_qty = q1.number_input(
                "الكمية بالكيلو:",
                min_value=0.001,
                value=1.0,
                step=0.1,
                format="%.3f",
                key="existing_btn_kg"
            )
            unit_cost = q2.number_input(
                "سعر شراء الكيلو:",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f",
                key="existing_btn_kg_cost"
            )
            ppc = 1

        if "existing_has_expiry" not in st.session_state:
            st.session_state["existing_has_expiry"] = False

        st.markdown("#### 📅 تاريخ الصلاحية")
        e1, e2 = st.columns(2)
        if e1.button("🚫 بدون تاريخ انتهاء", use_container_width=True):
            st.session_state["existing_has_expiry"] = False
            st.rerun()
        if e2.button("📅 تحديد تاريخ انتهاء", use_container_width=True):
            st.session_state["existing_has_expiry"] = True
            st.rerun()

        expiry_date = None
        if st.session_state["existing_has_expiry"]:
            expiry_date = st.date_input(
                "تاريخ انتهاء الصلاحية:",
                value=date.today(),
                min_value=date.today(),
                key="existing_btn_expiry_date"
            )

        if st.button(
            "➕ إضافة الكمية للصنف",
            type="primary",
            use_container_width=True
        ):
            st.session_state["inventory_confirm_pending_action"] = {
                "callback": add_stock_to_existing_item,
                "args": [branch_id, selected["id"], added_qty, unit_cost, unit_type, ppc, expiry_date],
                "summary": [
                    ("العملية", "إضافة كمية إلى صنف"),
                    ("الصنف", selected["item_name"]),
                    ("الكمية المضافة", f"{float(added_qty):,.3f}"),
                    ("سعر الشراء", f"{float(unit_cost):,.2f} د.ل"),
                    ("الصلاحية", str(expiry_date) if expiry_date else "بدون تاريخ انتهاء"),
                ],
            }
            st.rerun()

    # =========================================================
    # صنف جديد
    # =========================================================
    elif mode == "new":
        st.markdown("### ➕ إنشاء صنف جديد")
        c1, c2 = st.columns(2)
        item_code = c1.text_input("كود الصنف / الباركود:", key="new_btn_code")
        item_name = c2.text_input("اسم الصنف:", key="new_btn_name")

        if "new_unit_type" not in st.session_state:
            st.session_state["new_unit_type"] = "piece"

        u1, u2 = st.columns(2)
        if u1.button("🔢 قطعة", use_container_width=True):
            st.session_state["new_unit_type"] = "piece"
            st.rerun()
        if u2.button("⚖️ كجم", use_container_width=True):
            st.session_state["new_unit_type"] = "kg"
            st.rerun()

        unit_type = st.session_state["new_unit_type"]
        if unit_type == "piece":
            qty, cost, ppc = piece_input_fields("new_btn", 1)
            sale_label = "سعر بيع القطعة (د.ل):"
        else:
            q1, q2 = st.columns(2)
            qty = q1.number_input(
                "الكمية بالكيلو:",
                min_value=0.001,
                value=1.0,
                step=0.1,
                format="%.3f",
                key="new_btn_kg"
            )
            cost = q2.number_input(
                "سعر شراء الكيلو:",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f",
                key="new_btn_kg_cost"
            )
            ppc = 1
            sale_label = "سعر بيع الكيلو (د.ل):"

        sale_price = st.number_input(
            sale_label, min_value=0.0, value=0.0,
            step=0.5, format="%.2f", key="new_btn_sale_price"
        )

        if "new_has_expiry" not in st.session_state:
            st.session_state["new_has_expiry"] = False
        e1, e2 = st.columns(2)
        if e1.button("🚫 بدون صلاحية", use_container_width=True):
            st.session_state["new_has_expiry"] = False
            st.rerun()
        if e2.button("📅 تحديد الصلاحية", use_container_width=True):
            st.session_state["new_has_expiry"] = True
            st.rerun()

        expiry_date_new = None
        if st.session_state["new_has_expiry"]:
            expiry_date_new = st.date_input(
                "تاريخ انتهاء الصلاحية:",
                value=date.today(),
                min_value=date.today(),
                key="new_btn_expiry_date"
            )

        if st.button(
            "💾 إنشاء الصنف وحفظ الرصيد",
            type="primary",
            use_container_width=True
        ):
            st.session_state["inventory_confirm_pending_action"] = {
                "callback": create_new_inventory_item,
                "args": [branch_id, item_code, item_name, qty, cost, sale_price, unit_type, ppc, expiry_date_new],
                "summary": [
                    ("العملية", "إنشاء صنف جديد"),
                    ("الكود", item_code),
                    ("الصنف", item_name),
                    ("الكمية الافتتاحية", f"{float(qty):,.3f}"),
                    ("سعر الشراء", f"{float(cost):,.2f} د.ل"),
                    ("سعر البيع", f"{float(sale_price):,.2f} د.ل"),
                ],
            }
            st.rerun()

    # =========================================================
    # الصلاحيات
    # =========================================================
    else:
        st.markdown("### 📅 دفعات الصلاحية")
        conn = None
        try:
            conn = get_db_connection()
            batch_rows = conn.execute(
                """
                SELECT
                    b.id,
                    i.item_code,
                    i.item_name,
                    b.received_date,
                    b.expiry_date,
                    b.quantity,
                    b.remaining_quantity,
                    b.unit_cost,
                    b.source_type
                FROM inventory_batches b
                JOIN items i ON i.id = b.item_id
                WHERE b.branch_id = ?
                  AND b.expiry_date IS NOT NULL
                ORDER BY b.expiry_date ASC, i.item_name ASC
                """,
                (branch_id,)
            ).fetchall()

            if not batch_rows:
                st.info("لا توجد دفعات لها تاريخ انتهاء في هذا الفرع.")
                return

            today = date.today()
            batch_data = []
            for row in batch_rows:
                days_left = (row["expiry_date"] - today).days
                if days_left < 0:
                    status = f"🔴 منتهي منذ {abs(days_left)} يوم"
                elif days_left == 0:
                    status = "🔴 ينتهي اليوم"
                elif days_left <= 7:
                    status = f"🟠 متبقي {days_left} يوم"
                elif days_left <= 30:
                    status = f"🟡 متبقي {days_left} يوم"
                else:
                    status = f"🟢 متبقي {days_left} يوم"

                batch_data.append({
                    "رقم الدفعة": row["id"],
                    "الكود": row["item_code"],
                    "اسم الصنف": row["item_name"],
                    "تاريخ الدخول": row["received_date"],
                    "تاريخ الانتهاء": row["expiry_date"],
                    "كمية الدفعة": float(row["quantity"] or 0),
                    "المتبقي": float(row["remaining_quantity"] or 0),
                    "تكلفة الوحدة": float(row["unit_cost"] or 0),
                    "الحالة": status,
                    "المصدر": "مشتريات" if row["source_type"] == "purchase" else "إضافة مخزون",
                })

            batch_df = pd.DataFrame(batch_data)
            st.dataframe(batch_df, use_container_width=True, hide_index=True)
            st.download_button(
                "📥 تصدير دفعات الصلاحية إلى Excel",
                data=_excel_bytes(batch_df, "Expiry_Batches"),
                file_name=f"expiry_batches_{branch_id}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        except Exception as e:
            st.error("❌ تعذر تحميل دفعات الصلاحية.")
            st.code(str(e))
        finally:
            if conn:
                conn.close()

