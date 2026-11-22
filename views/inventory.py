_PAGE_ERROR_UI_REVISION = 70
from views.page_guard import show_operation_error
from control_services import weighted_inventory_receipt
from views.number_format import gross_margin_display
from control_services import ensure_governance_schema, set_product_expiry_policy
from views.number_format import excel_literal_text
from views.number_format import decimal_display
from views.ui_feedback import ui_field, ui_form, ui_submit, notify_success, reset_page_fields
from views.ui_common import back_button
from views.ui_common import item_alerts
import streamlit as st
import pandas as pd
import io
from datetime import date, datetime
from database import get_db_connection



def _as_date(value):
    """Normalize SQLite/PostgreSQL date values to datetime.date."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # Handles YYYY-MM-DD and ISO datetime strings.
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None

def ensure_inventory_columns():
    conn = None
    try:
        # Schema maintenance is local-only and must never enter sync_queue.
        from offline_store import get_local_connection
        conn = get_local_connection(queue_writes=False)
        # SQLite does not support PostgreSQL's ADD COLUMN IF NOT EXISTS syntax.
        # Check the existing columns first, then add only the missing ones.
        existing_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(items)").fetchall()
        }
        if "unit_type" not in existing_columns:
            conn.execute("ALTER TABLE items ADD COLUMN unit_type TEXT DEFAULT 'piece'")
        if "pieces_per_carton" not in existing_columns:
            conn.execute("ALTER TABLE items ADD COLUMN pieces_per_carton INTEGER DEFAULT 1")
        if "scale_code" not in existing_columns:
            conn.execute("ALTER TABLE items ADD COLUMN scale_code TEXT")
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
        # Remove only legacy queued schema-normalization statements. They are
        # local maintenance, not branch business operations or stock changes.
        def _normal_sql(value):
            return " ".join(str(value or "").lower().split())

        maintenance_sql = {
            "update items set unit_type = 'piece' where unit_type is null or trim(unit_type) = ''",
            "update items set pieces_per_carton = 1 where pieces_per_carton is null or pieces_per_carton < 1",
        }
        queued = conn.execute(
            "SELECT id, sql_text, params_json FROM sync_queue WHERE sync_status = 'pending'"
        ).fetchall()
        obsolete_ids = [
            (row["id"],) for row in queued
            if _normal_sql(row["sql_text"]) in maintenance_sql
            and str(row["params_json"] or "[]").strip() == "[]"
        ]
        if obsolete_ids:
            conn.executemany("UPDATE sync_queue SET sync_status='ignored',sync_error='Verified schema maintenance; retained for audit' WHERE id = ?", obsolete_ids)
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
            "SELECT id, branch_name, branch_type FROM branches ORDER BY id ASC"
        ).fetchall()
    finally:
        if conn:
            conn.close()


def get_branch_items_rows(branch_id):
    conn = None
    try:
        conn = get_db_connection()
        ensure_governance_schema(conn); conn.commit()
        return conn.execute(
            """
            SELECT id, item_code, item_name, quantity, buy_price,
                   avg_cost, sale_price, scale_price,
                   COALESCE(unit_type, 'piece') AS unit_type,
                   COALESCE(pieces_per_carton, 1) AS pieces_per_carton,
                   COALESCE(scale_code, '') AS scale_code,
                   (SELECT p.shelf_life_days FROM product_expiry_policies p
                    WHERE p.item_id=items.id AND p.branch_id=items.branch_id) AS shelf_life_days
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
            nearest = _as_date(row["nearest_expiry"])

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


def add_stock_to_existing_item(branch_id,item_id,added_quantity,unit_buy_price=None,unit_type=None,pieces_per_carton=None,expiry_date=None,operation_uuid=None):
    conn=None
    try:
        import uuid
        from views.item_surplus import add_surplus
        conn=get_db_connection()
        result=add_surplus(conn,branch_id,item_id,added_quantity,st.session_state.get('user_id'),operation_uuid or str(uuid.uuid4()))
        conn.commit()
        st.session_state.pop('inventory_surplus_uuid',None)
        _inventory_done('تم تسجيل فائض صنف.' if not result['already_applied'] else 'فائض صنف محفوظ بالفعل.')
    except Exception as e:
        if conn:conn.rollback()
        st.error('تعذر تسجيل فائض صنف.')
        show_operation_error(e,announce=False,context='فائض صنف')
    finally:
        if conn:conn.close()



def create_new_inventory_item(
    branch_id, item_code, item_name, initial_quantity,
    unit_buy_price, sale_price, unit_type, pieces_per_carton,
    expiry_date=None, shelf_life_days=None, barcode_payload=None
):
    conn = None
    try:
        item_code = normalize_barcode(item_code)
        item_name = item_name.strip()
        if not item_code:
            barcode_payload=dict(barcode_payload or {})
            item_code=normalize_barcode(barcode_payload.get('manufacturer') or barcode_payload.get('internal') or '')
            if not item_code:
                from views.item_barcodes import internal_code
                item_code=internal_code();barcode_payload['internal']=item_code
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
        assert_barcode_available(conn,item_code,item_name)
        branch_row = conn.execute("SELECT branch_name, branch_type FROM branches WHERE id=?", (branch_id,)).fetchone()
        is_main_warehouse = bool(branch_row) and (
            str(branch_row["branch_type"] or "").strip() == "مخزن"
            or "رئيس" in str(branch_row["branch_name"] or "")
        )
        if not is_main_warehouse:
            main_item = conn.execute(
                """SELECT i.sale_price FROM items i JOIN branches b ON b.id=i.branch_id
                   WHERE i.item_code=? AND (b.branch_type='مخزن' OR b.branch_name LIKE '%رئيس%')
                   ORDER BY i.id LIMIT 1""", (item_code,)
            ).fetchone()
            if not main_item:
                raise ValueError("يجب تعريف الصنف وسعره أولاً في المخزن الرئيسي قبل إضافته إلى أي فرع.")
            sale_price = float(main_item["sale_price"] or 0)

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
        if shelf_life_days is not None:
            ensure_governance_schema(conn)
            set_product_expiry_policy(conn, branch_id, new_item_id, shelf_life_days, st.session_state.get("user_id"))

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

        if barcode_payload is not None:
            from views.item_barcodes import save_links
            save_links(conn,st.session_state.get('user_id'),branch_id,item_code,barcode_payload)
        conn.commit()

        label = "كجم" if unit_type == "kg" else "قطعة"
        _inventory_done(
            f"تم إنشاء الصنف ({item_name}) برصيد أولي {decimal_display(initial_quantity, 3)} {label}."
            + "\n" + gross_margin_display(unit_buy_price, sale_price)
        )
    except Exception as e:
        if conn:
            conn.rollback()
        st.error("❌ تعذر إنشاء الصنف الجديد.")
        show_operation_error(e, announce=False, context='views/inventory.py:440')
    finally:
        if conn:
            conn.close()


def piece_input_fields(prefix, default_pieces=1):
    c1, c2 = st.columns(2)
    qty = ui_field(c1.number_input, "inventory:410", 
        "الكمية بالقطعة:",
        min_value=1.0,
        value=1.0,
        step=1.0,
        format="%.0f",
        key=f"{prefix}_piece_qty"
    )
    unit_cost = ui_field(c2.number_input, "inventory:418", 
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
        show_operation_error(e, announce=False, context='views/inventory.py:484')
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
        excel_literal_text(writer)
    return output.getvalue()


def _update_items_from_editor(branch_id, original_rows, edited_df):
    """يحفظ تعديلات جدول الأصناف، ويسجل أي تغيير مباشر في الكمية."""
    conn = None
    try:
        original = {int(r["id"]): r for r in original_rows}
        margin_messages = []
        conn = get_db_connection()
        branch_row = conn.execute("SELECT branch_name, branch_type FROM branches WHERE id=?", (branch_id,)).fetchone()
        is_main_warehouse = bool(branch_row) and (
            str(branch_row["branch_type"] or "").strip() == "مخزن"
            or "رئيس" in str(branch_row["branch_name"] or "")
        )

        for _, row in edited_df.iterrows():
            item_id = int(row["id"])
            old = original.get(item_id)
            if not old:
                continue

            item_code = str(row["كود الصنف"] or "").strip()
            item_name = str(row["اسم الصنف"] or "").strip()
            scale_code = str(row.get("كود الميزان", "") or "").strip()
            unit_ar = str(row["الوحدة"] or "قطعة").strip()
            unit_type = "kg" if unit_ar == "كجم" else "piece"
            ppc = 1
            new_qty = float(row["الكمية"] or 0)
            # الشراء ومتوسط التكلفة قيم محاسبية: لا تقبل التعديل اليدوي من شاشة المخزون.
            buy_price = float(old["buy_price"] or 0)
            avg_cost = float(old["avg_cost"] or 0)
            if not is_main_warehouse:
                # بيانات تعريف الصنف مركزية؛ الفرع يعدل كميته فقط.
                item_code = str(old["item_code"] or "").strip()
                item_name = str(old["item_name"] or "").strip()
                scale_code = str(old["scale_code"] or "").strip()
                unit_type = str(old["unit_type"] or "piece")
            if scale_code != str(old["scale_code"] or "").strip():
                from views.item_barcodes import guard_scale
                guard_scale(conn,item_code,scale_code)
            requested_sale_price = float(row["سعر البيع"] or 0)
            sale_price = requested_sale_price if is_main_warehouse else float(old["sale_price"] or 0)

            if not item_code or not item_name:
                raise ValueError("كود الصنف واسم الصنف لا يمكن أن يكونا فارغين.")
            if new_qty < 0 or buy_price < 0 or avg_cost < 0 or sale_price < 0:
                raise ValueError(f"لا يمكن إدخال قيمة سالبة للصنف: {item_name}")

            if item_code != str(old["item_code"] or "").strip() or item_name != str(old["item_name"] or "").strip():
                assert_barcode_available(conn,item_code,item_name,exclude_id=item_id,
                    previous_code=old['item_code'],previous_name=old['item_name'],propagates=is_main_warehouse)
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

            if abs(sale_price - float(old["sale_price"] or 0)) > 1e-9:
                margin_messages.append(item_name + ': ' + gross_margin_display(None if old['avg_cost'] is None and old['buy_price'] is None else avg_cost, sale_price))
            old_qty = float(old["quantity"] or 0)
            delta = new_qty - old_qty

            # Skip unchanged rows entirely: no unnecessary SQL, queue entries,
            # or cross-branch propagation when the user clicks Save.
            unchanged = (
                item_code == str(old["item_code"] or "").strip()
                and item_name == str(old["item_name"] or "").strip()
                and scale_code == str(old["scale_code"] or "").strip()
                and unit_type == str(old["unit_type"] or "piece")
                and ppc == int(old["pieces_per_carton"] or 1)
                and abs(delta) <= 1e-9
                and abs(sale_price - float(old["sale_price"] or 0)) <= 1e-9
            )
            if "مدة صلاحية الإنتاج بالأيام" in row:
                requested_days = row["مدة صلاحية الإنتاج بالأيام"]
                old_days = old["shelf_life_days"] if "shelf_life_days" in old.keys() else None
                if pd.isna(requested_days):
                    if old_days is not None:
                        raise ValueError("لا يمكن مسح مدة صلاحية معتمدة ضمن تعديل الأصناف؛ أدخل مدة صحيحة.")
                elif old_days is None or float(requested_days) != float(old_days):
                    if not float(requested_days).is_integer():
                        raise ValueError("مدة صلاحية الإنتاج يجب أن تكون عدداً صحيحاً بالأيام.")
                    ensure_governance_schema(conn)
                    set_product_expiry_policy(conn, branch_id, item_id, int(requested_days), st.session_state.get("user_id"))
            if unchanged:
                continue

            conn.execute(
                """
                UPDATE items
                SET item_code = ?,
                    item_name = ?,
                    scale_code = ?,
                    quantity = ?,
                    buy_price = ?,
                    avg_cost = ?,
                    sale_price = ?,
                    unit_type = ?,
                    pieces_per_carton = ?
                WHERE id = ? AND branch_id = ?
                """,
                (
                    item_code, item_name, scale_code, new_qty, buy_price, avg_cost,
                    sale_price, unit_type, ppc, item_id, branch_id
                )
            )

            # بيانات تعريف الصنف مركزية: أي تعديل من المخزن الرئيسي يعمم على كل الفروع.
            # نطابق بالكود القديم حتى تغيير كود الصنف نفسه ينتشر بصورة صحيحة.
            if is_main_warehouse:
                old_code = str(old["item_code"] or "").strip()
                conn.execute(
                    """UPDATE items
                       SET item_code=?, item_name=?, scale_code=?, sale_price=?,
                           unit_type=?, pieces_per_carton=?
                       WHERE item_code=? AND NOT (id=? AND branch_id=?)""",
                    (item_code, item_name, scale_code, sale_price, unit_type, ppc,
                     old_code, item_id, branch_id)
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
        _inventory_done("تم حفظ تعديلات الأصناف بنجاح." + ("\n" + "\n".join(margin_messages) if margin_messages else ""))
    except Exception as e:
        if conn:
            conn.rollback()
        st.error("❌ تعذر حفظ تعديلات الأصناف.")
        show_operation_error(e, announce=False, context='views/inventory.py:659')
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
        show_operation_error(e, announce=False, context='views/inventory.py:711')
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
            "كود الميزان": row["scale_code"] or "",
            "الوحدة": "كجم" if (row["unit_type"] or "piece") == "kg" else "قطعة",
            "الكمية": float(row["quantity"] or 0),
            "سعر الشراء": float(row["buy_price"] or 0),
            "متوسط التكلفة": float(row["avg_cost"] or 0),
            "سعر البيع": float(row["sale_price"] or 0),
            "سعر الميزان": float(row["scale_price"]) if row["scale_price"] is not None and row["unit_type"]=="kg" else None,
        })
    if st.session_state.get("role") == "Super_Admin":
        for record, source in zip(data, rows):
            record["مدة صلاحية الإنتاج بالأيام"] = source["shelf_life_days"] if "shelf_life_days" in source.keys() else None
    return pd.DataFrame(data)


@st.dialog("✅ تمت العملية بنجاح", dismissible=False)
def _inventory_success_dialog():
    st.success(st.session_state.get("inventory_success_message", "تمت العملية بنجاح."))
    if st.button("موافق", type="primary", use_container_width=True, key="inventory_success_ok"):
        reset_page_fields()
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
        st.stop()

    try:
        ensure_inventory_columns()
    except Exception as e:
        st.error("❌ تعذر تجهيز حقول وحدات المخزون.")
        show_operation_error(e, announce=False, context='views/inventory.py:790')
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
        show_operation_error(e, announce=False, context='views/inventory.py:803')
        return

    if not branches:
        st.warning("⚠️ يرجى إنشاء مخزن أو فرع أولاً.")
        return

    b_dict = {b["branch_name"]: b["id"] for b in branches}
    b_type = {b["branch_name"]: (b["branch_type"] if "branch_type" in b.keys() else "") for b in branches}
    selected_branch = ui_field(st.selectbox, "inventory:734", 
        "🏢 اختر المخزن أو الفرع:",
        list(b_dict.keys()),
        key="inventory_branch"
    )
    branch_id = b_dict[selected_branch]
    is_main_warehouse = (str(b_type.get(selected_branch) or "").strip() == "مخزن" or "رئيس" in selected_branch)

    try:
        existing_items = get_branch_items_rows(branch_id)
    except Exception as e:
        st.error("❌ تعذر تحميل أصناف الفرع.")
        show_operation_error(e, announce=False, context='views/inventory.py:824')
        existing_items = []

    if "inventory_mode" not in st.session_state:
        st.session_state["inventory_mode"] = "list"

    if not st.session_state.get("inventory_entry_lock"):
        mode_labels = {
            "📋 الأصناف والتعديل": "list",
            "➕ صنف جديد": "new",
            "فائض صنف": "add",
            "📅 الصلاحيات": "expiry",
        }
        current_label = next((k for k,v in mode_labels.items() if v == st.session_state["inventory_mode"]), list(mode_labels)[0])
        selected_label = ui_field(st.selectbox, "inventory:759", "اختر العملية:", list(mode_labels), index=list(mode_labels).index(current_label), key="inventory_action_dropdown")
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


        if is_main_warehouse:
            st.info("🔒 سعر الشراء ومتوسط التكلفة للعرض فقط. بيانات الصنف وسعر البيع تُعدّل من المخزن الرئيسي وتُعمم تلقائياً على جميع الفروع.")
        else:
            st.info("🔒 في الفروع يمكن تعديل الكمية فقط. بيانات الصنف والأسعار مركزية من المخزن الرئيسي.")

        edited_df = ui_field(st.data_editor, "inventory:789", 
            original_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key=f"inventory_editor_{branch_id}",
            disabled=(
                ["id", "سعر الشراء", "متوسط التكلفة", "سعر الميزان"]
                if is_main_warehouse
                else ["id", "كود الصنف", "اسم الصنف", "كود الميزان", "الوحدة", "سعر الشراء", "متوسط التكلفة", "سعر البيع", "سعر الميزان"]
            ),
            column_config={
                "مدة صلاحية الإنتاج بالأيام": st.column_config.NumberColumn("مدة صلاحية الإنتاج بالأيام", min_value=1, max_value=36500, step=1, format="%d", help="اختياري، يعتمد بواسطة Super_Admin. القيمة الفارغة تعني أن مدة الإنتاج غير معروفة."),
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "كود الميزان": st.column_config.TextColumn("كود الميزان / PLU", help="الكود الداخلي الذي يطبعه الميزان للصنف، مثل 14000"),
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
        selected_label = ui_field(st.selectbox, "inventory:841", 
            "اختر صنفًا لعمليات النسخ أو الحذف:",
            list(item_map.keys()),
            key=f"inventory_manage_item_{branch_id}"
        )
        selected = item_map[selected_label]
        _existing_barcode_editor(selected,branch_id)
        barcode_label_panel(_barcode_for_existing_print(selected,branch_id),selected['item_name'],selected['sale_price'],branch_id,
            key='inventory_existing_label_'+str(branch_id)+'_'+str(selected['id']))

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
        st.markdown('### فائض صنف')
        if is_main_warehouse:
            st.info('اختر الفرع.')
            return
        if not existing_items:
            st.info('لا توجد أصناف في هذا الفرع.')
            return
        item_map={f"{r['item_name']} — {r['item_code']}":r for r in existing_items}
        selected=item_map[st.selectbox('اختر الصنف:',list(item_map),key='inventory_add_item')]
        unit='كجم' if selected['unit_type']=='kg' else 'قطعة'
        qty=st.number_input('الكمية ('+unit+'):',min_value=0.001 if unit=='كجم' else 1.0,value=1.0,step=0.001 if unit=='كجم' else 1.0,format='%.3f',key='inventory_surplus_quantity')
        if st.button('فائض صنف',type='primary',use_container_width=True):
            import uuid
            identity=st.session_state.setdefault('inventory_surplus_uuid',str(uuid.uuid4()))
            add_stock_to_existing_item(branch_id,selected['id'],qty,operation_uuid=identity)
            st.rerun()

    elif mode == "new":
        st.markdown("### ➕ إنشاء صنف جديد")
        c1, c2 = st.columns(2)
        c1.button('إنشاء باركود',key='create_new_item_barcode',on_click=_generate_new_item_barcode,
            args=(branch_id,),disabled=not is_main_warehouse)
        item_code = ui_field(c1.text_input, "inventory:991", "كود الصنف / الباركود:", key="new_btn_code")
        item_name = ui_field(c2.text_input, "inventory:992", "اسم الصنف:", key="new_btn_name")
        barcode_payload_new=None
        if is_main_warehouse:
            st.button('إنشاء باركود داخلي إضافي',key='new_alias_generate',on_click=_set_internal_barcode,args=('new_alias_internal',))
            barcode_payload_new=_barcode_fields('new_alias')


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
            qty = ui_field(q1.number_input, "inventory:1011", 
                "الكمية بالكيلو:",
                min_value=0.001,
                value=1.0,
                step=0.1,
                format="%.3f",
                key="new_btn_kg"
            )
            cost = ui_field(q2.number_input, "inventory:1019", 
                "سعر شراء الكيلو:",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f",
                key="new_btn_kg_cost"
            )
            ppc = 1
            sale_label = "سعر بيع الكيلو (د.ل):"

        if is_main_warehouse:
            sale_price = ui_field(st.number_input, "inventory:1031", 
                sale_label, min_value=0.0, value=0.0,
                step=0.5, format="%.2f", key="new_btn_sale_price"
            )
        else:
            sale_price = 0.0
            st.info("🔒 سعر البيع سيُسحب تلقائياً من نفس كود الصنف في المخزن الرئيسي.")

        if "new_has_expiry" not in st.session_state:
            st.session_state["new_has_expiry"] = False
        e1, e2 = st.columns(2)
        if e1.button("🚫 بدون صلاحية", use_container_width=True):
            st.session_state["new_has_expiry"] = False
            st.rerun()
        if e2.button("📅 تحديد الصلاحية", use_container_width=True):
            st.session_state["new_has_expiry"] = True
            st.rerun()

        if item_code and item_name:
            barcode_label_panel(item_code,item_name,sale_price,branch_id,key='inventory_new_label_'+str(branch_id))
        expiry_date_new = None
        if st.session_state["new_has_expiry"]:
            expiry_date_new = ui_field(st.date_input, "inventory:1051", 
                "تاريخ انتهاء الصلاحية:",
                value=date.today(),
                min_value=date.today(),
                key="new_btn_expiry_date"
            )

        shelf_life_days_new = None
        if st.session_state.get("role") == "Super_Admin":
            shelf_life_days_new = ui_field(st.number_input, "inventory:production_shelf_life", "مدة صلاحية الإنتاج بالأيام", min_value=1, max_value=36500, value=None, step=1, key="new_production_shelf_life")

        if st.button(
            "💾 إنشاء الصنف وحفظ الرصيد",
            type="primary",
            use_container_width=True
        ):
            st.session_state["inventory_confirm_pending_action"] = {
                "callback": create_new_inventory_item,
                "args": [branch_id, item_code, item_name, qty, cost, sale_price, unit_type, ppc, expiry_date_new, shelf_life_days_new, barcode_payload_new],
                "summary": [
                    ("العملية", "إنشاء صنف جديد"),
                    ("الكود", item_code),
                    ("الصنف", item_name),
                    ("الكمية الافتتاحية", f"{decimal_display(float(qty), 3)}"),
                    ("سعر الشراء", f"{decimal_display(float(cost), 2)} د.ل"),
                    ("سعر البيع", f"{decimal_display(float(sale_price), 2)} د.ل"),
                    ("هامش الربح الإجمالي", gross_margin_display(cost, sale_price) if is_main_warehouse else "يُحسب بسعر المخزن الرئيسي عند الحفظ"),
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
                expiry_date = _as_date(row["expiry_date"])
                if expiry_date is None:
                    continue
                days_left = (expiry_date - today).days
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
                    "تاريخ الانتهاء": expiry_date,
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
            show_operation_error(e, announce=False, context='views/inventory.py:1244')
        finally:
            if conn:
                conn.close()




def normalize_barcode(value):
    import math
    if value is None:
        return ''
    if isinstance(value, float):
        if not math.isfinite(value):
            return ''
        if not value.is_integer():
            raise ValueError('الباركود الرقمي يجب أن يكون عدداً صحيحاً أو نصاً')
        return str(int(value))
    return str(value).strip()


def _barcode_name(value):
    import unicodedata
    return ' '.join(unicodedata.normalize('NFC',str(value or '')).casefold().split())


def assert_barcode_available(conn, code, name, exclude_id=None, previous_code=None, previous_name=None, propagates=False):
    code=normalize_barcode(code)
    from views.item_barcodes import guard_primary,links
    guard_primary(conn,code)
    if previous_code and str(previous_code)!=code and links(conn,str(previous_code)):
        raise ValueError('احتفظ بكود الصنف المرتبط؛ عدّل باركوداته من حقول الباركود دون تغيير هويته')
    if not code or not _barcode_name(name):
        raise ValueError('كود الصنف واسم الصنف مطلوبان')
    import sqlite3
    raw=getattr(conn,'_conn',conn)
    if isinstance(raw,sqlite3.Connection):
        if not raw.in_transaction:conn.execute('BEGIN IMMEDIATE')
    else:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(?,0))',('abuzaid:barcode:'+code,))
    names={_barcode_name(name)}
    if propagates and code==normalize_barcode(previous_code):names.add(_barcode_name(previous_name))
    rows=conn.execute('SELECT id,item_name FROM items WHERE item_code=?',(code,)).fetchall()
    if any((exclude_id is None or int(row['id'])!=int(exclude_id)) and _barcode_name(row['item_name']) not in names for row in rows):
        raise ValueError('هذا الباركود مرتبط بصنف مختلف؛ لم يتم استبداله أو دمج الصنفين')
    return code


def generate_internal_barcode(conn):
    import secrets
    for _ in range(20):
        # Alphanumeric prefix never enters the numeric scale-price/weight format.
        code='AZ'+str(secrets.randbits(64)).zfill(20)
        if not conn.execute('SELECT 1 FROM items WHERE item_code=? LIMIT 1',(code,)).fetchone():
            return code
    raise ValueError('تعذر إنشاء كود داخلي فريد؛ لم يتغير أي صنف')


def _label_access(conn, branch_id):
    from control_services import account_login_allowed
    role=st.session_state.get('role','');uid=st.session_state.get('user_id')
    row=conn.execute('SELECT role,branch_id,is_active FROM users WHERE id=?',(uid,)).fetchone()
    allowed={'Super_Admin','Admin','Manager','General_Supervisor','Supervisor','Branch_Supervisor'}
    if not row or not row['is_active'] or row['role']!=role or role not in allowed or not account_login_allowed(conn,uid):
        raise PermissionError('طباعة الملصقات تتطلب صلاحية المخزون الحالية')
    if role in {'Supervisor','Branch_Supervisor'} and str(row['branch_id'])!=str(branch_id):
        raise PermissionError('الفرع خارج صلاحية المستخدم')


def barcode_svg(code, width_mm=60, bar_height_mm=12):
    import base64
    try:
        from barcode.codex import Code128
        from barcode.writer import SVGWriter
    except ModuleNotFoundError as exc:
        if exc.name!='barcode':raise
        import sys
        from pathlib import Path
        vendor=str(Path(__file__).resolve().parents[1]/'_internal')
        if vendor not in sys.path:sys.path.insert(0,vendor)
        from barcode.codex import Code128
        from barcode.writer import SVGWriter
    code=normalize_barcode(code)
    if not code or len(code)>80 or any(ord(c)<32 or ord(c)>126 for c in code):
        raise ValueError('Code 128 يحتاج كوداً صالحاً للطباعة بحروف وأرقام إنجليزية؛ لم يتم تغيير الكود الأصلي')
    symbol=Code128(code,writer=SVGWriter())
    modules=len(symbol.build()[0]);module=0.254
    required=(modules+20)*module
    if required>float(width_mm)-4:
        raise ValueError('مقاس الملصق ضيق لهذا الكود؛ اختر عرضاً لا يقل عن '+str(int(required+5))+' مم دون تصغير الباركود وإفساد قراءته')
    data=symbol.render({'module_width':module,'module_height':float(bar_height_mm),'quiet_zone':10*module,'font_size':0,'write_text':False,'background':'white','foreground':'black'})
    return data.decode('utf-8')


def barcode_labels_html(code,name,price,count=1,width_mm=60,height_mm=40):
    import html,base64,math
    count=int(count);width=float(width_mm);height=float(height_mm);price=float(price)
    if not 1<=count<=500 or not 30<=width<=150 or not 25<=height<=100 or not math.isfinite(price) or price<0:
        raise ValueError('عدد الملصقات أو المقاس أو السعر غير صالح')
    svg=barcode_svg(code,width,max(8,min(15,height-18)))
    image=base64.b64encode(svg.encode()).decode()
    label=('<section class="label"><div class="name">'+html.escape(str(name))+'</div><div class="price">'
           +f'{price:.2f} د.ل'+'</div><img alt="Code 128" src="data:image/svg+xml;base64,'+image+'">'
           +'<div class="code" dir="ltr">'+html.escape(normalize_barcode(code))+'</div></section>')
    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>
    @page {{size:{width}mm {height}mm;margin:0}}
    body{{margin:0;background:white;color:black;font-family:Arial,sans-serif}}
    .tools{{padding:10px;direction:rtl}}
    .label{{box-sizing:border-box;width:{width}mm;height:{height}mm;padding:2mm;overflow:hidden;text-align:center;break-after:page;page-break-after:always}}
    .label:last-child{{break-after:auto;page-break-after:auto}}
    .name{{font-size:10pt;height:8mm;overflow:hidden;line-height:4mm}}.price{{font-size:10pt;height:4.5mm}}
    img{{display:block;margin:0 auto}}.code{{font-family:monospace;font-size:8pt;white-space:nowrap}}
    @media print{{.tools{{display:none}}}}
    </style></head><body><div class="tools"><button type="button" onclick="window.print()">طباعة الملصقات واختيار الطابعة</button>
    <p>اختر الطابعة ومقاس الملصق من نافذة الطباعة، والحجم الفعلي 100% دون ملاءمة تلقائية.</p></div>{label*count}</body></html>'''


def barcode_label_panel(code,name,price,branch_id,key='barcode_labels'):
    import sqlite3
    if st.session_state.get('role') not in {'Super_Admin','Admin','Manager','General_Supervisor','Supervisor','Branch_Supervisor'}:
        return
    with st.expander('🏷️ معاينة الباركود وطباعة الملصقات'):
        from pathlib import Path
        import os
        if os.name=='nt':
            from sherif_paths import local_db
            conn=sqlite3.connect(local_db().resolve().as_uri()+'?mode=ro',uri=True)
            conn.row_factory=sqlite3.Row
        else:
            conn=get_db_connection()
        try:
            _label_access(conn,branch_id)
            linked=conn.execute('SELECT item_name FROM items WHERE item_code=?',(normalize_barcode(code),)).fetchall()
            from views.item_barcodes import exists
            if exists(conn):
                linked+=conn.execute('SELECT i.item_name FROM items i JOIN item_barcodes b ON b.item_code=i.item_code WHERE b.namespace=? AND b.barcode=?',('plain',normalize_barcode(code))).fetchall()
            if any(_barcode_name(row['item_name'])!=_barcode_name(name) for row in linked):
                raise PermissionError('الكود مرتبط باسم صنف مختلف؛ احفظ بيانات الصنف الصحيحة قبل طباعة الملصق.')
        except PermissionError as exc:st.warning(str(exc));return
        finally:conn.close()
        cols=st.columns(3)
        count=cols[0].number_input('عدد الملصقات',min_value=1,max_value=500,value=1,step=1,key=key+'_count')
        width=cols[1].number_input('عرض الملصق (مم)',min_value=30,max_value=150,value=60,step=1,key=key+'_width')
        height=cols[2].number_input('ارتفاع الملصق (مم)',min_value=25,max_value=100,value=40,step=1,key=key+'_height')
        st.caption('يُطبع الكود كما هو، ولا تتغير بيانات الصنف. اختيار الطابعة من نافذة الطباعة في المتصفح.')
        if st.button('معاينة وطباعة الباركود',key=key+'_preview'):
            try:
                document=barcode_labels_html(code,name,price,count,width,height)
                st.components.v1.html(document,height=420,scrolling=True)
                st.download_button('تنزيل ملصقات الطباعة',document.encode('utf-8'),'barcode_labels.html','text/html',key=key+'_download')
            except (ValueError,ImportError) as exc:st.warning(str(exc))


def _generate_new_item_barcode(branch_id):
    if str(st.session_state.get('new_btn_code','')).strip():
        st.warning('الباركود الحالي محفوظ كما هو؛ لا يُستبدل كود المصنع.');return
    conn=get_db_connection()
    try:
        _label_access(conn,branch_id)
        branch=conn.execute('SELECT branch_name,branch_type FROM branches WHERE id=?',(branch_id,)).fetchone()
        if not branch or not (str(branch['branch_type'] or '').strip()=='مخزن' or 'رئيس' in str(branch['branch_name'] or '')):
            raise PermissionError('يُعرّف الكود الجديد في المخزن الرئيسي أولاً.')
        st.session_state['new_btn_code']=generate_internal_barcode(conn)
    except (ValueError,PermissionError) as exc:st.warning(str(exc))
    finally:conn.close()


def _barcode_fields(prefix,values=None):
    values=values or {}
    return {'manufacturer':ui_field(st.text_input,'barcode:manufacturer','باركود المصنع الأصلي',value=values.get('manufacturer',''),key=prefix+'_manufacturer'),
        'internal':ui_field(st.text_input,'barcode:internal','الباركود الداخلي',value=values.get('internal',''),key=prefix+'_internal'),
        'extra':ui_field(st.text_area,'barcode:extra','باركودات إضافية — كل كود في سطر',value=values.get('extra',''),key=prefix+'_extra'),
        'scale':ui_field(st.text_area,'barcode:scale','أكواد الميزان / PLU — كل كود في سطر',value=values.get('scale',''),key=prefix+'_scale')}


def _set_internal_barcode(key):
    if str(st.session_state.get(key,'')).strip():return
    from views.item_barcodes import internal_code
    st.session_state[key]=internal_code()


def _existing_barcode_editor(item,branch_id):
    if st.session_state.get('role') not in ('Super_Admin','Admin','Manager'):return
    c=get_db_connection()
    try:
        branch=c.execute('SELECT branch_name,branch_type FROM branches WHERE id=?',(branch_id,)).fetchone()
        if not branch or not (branch['branch_type']=='مخزن' or 'رئيس' in str(branch['branch_name'])):return
        from views.item_barcodes import links
        rows=[dict(r) for r in links(c,item['item_code'])]
    finally:c.close()
    values={kind:'\n'.join(str(r['barcode']) for r in rows if r['kind']==kind) for kind in ('manufacturer','internal','extra','scale')}
    prefix='item_barcodes_'+str(branch_id)+'_'+str(item['id'])
    st.markdown('#### باركودات الصنف')
    st.button('إنشاء باركود داخلي',key=prefix+'_generate',on_click=_set_internal_barcode,args=(prefix+'_internal',))
    payload=_barcode_fields(prefix,values)
    if st.button('حفظ باركودات الصنف',key=prefix+'_save'):
        c=get_db_connection()
        try:
            from views.item_barcodes import save_links
            save_links(c,st.session_state.get('user_id'),branch_id,item['item_code'],payload)
            c.commit();notify_success('حُفظت باركودات الصنف؛ تُرسل عبر المزامنة الحالية.',reset=False);st.rerun()
        except Exception as exc:
            c.rollback();show_operation_error(exc, announce=True, context='views/inventory.py:1445')
        finally:c.close()


def _barcode_for_existing_print(item,branch_id):
    c=get_db_connection()
    try:
        from views.item_barcodes import links
        options=list(dict.fromkeys([str(item['item_code'])]+[str(r['barcode']) for r in links(c,item['item_code']) if r['namespace']=='plain']))
    finally:c.close()
    if len(options)==1:return options[0]
    return st.selectbox('الباركود المطلوب طباعته',options,key='item_print_barcode_'+str(branch_id)+'_'+str(item['id']))
