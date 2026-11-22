_PAGE_ERROR_UI_REVISION = 70
from views.page_guard import show_operation_error
from views.ui_feedback import ui_field, ui_form, ui_submit, notify_success, reset_page_fields
from views.ui_common import back_button
from datetime import date, datetime
import io

import pandas as pd
import streamlit as st

from database import get_db_connection


REQUIRED_COLUMNS = [
    "كود الصنف",
    "اسم الصنف",
    "الوحدة",
    "الكمية",
    "سعر الشراء",
    "سعر البيع",
]


def clean_code(value):
    """Preserve text identifiers; remove Excel's trailing .0 on numeric codes."""
    from views.inventory import normalize_barcode
    if pd.isna(value):return ''
    return normalize_barcode(value)


def clean_text(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def clean_number(value, default=0.0):
    if pd.isna(value) or str(value).strip() == "":
        return float(default)
    value = str(value).strip().replace(",", "")
    return float(value)


def clean_unit(value):
    value = clean_text(value).lower()
    piece_values = {"قطعة", "قطعه", "piece", "pcs", "pc"}
    kg_values = {"كجم", "كيلو", "كيلوجرام", "kg", "kilogram"}

    if value in piece_values:
        return "piece"
    if value in kg_values:
        return "kg"

    raise ValueError("الوحدة يجب أن تكون قطعة أو كجم فقط.")


def unit_arabic(unit_type):
    return "قطعة" if unit_type == "piece" else "كجم"


def clean_expiry(value):
    if pd.isna(value) or str(value).strip() == "":
        return None

    try:
        return pd.to_datetime(value).date()
    except Exception:
        raise ValueError(f"تاريخ الصلاحية ({value}) غير صحيح.")


def ensure_inventory_batches(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory_batches (
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
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_inventory_batches_expiry
        ON inventory_batches(branch_id, expiry_date)
    """)
    conn.commit()


def add_batch(conn, item_id, branch_id, qty, buy_price, expiry_date,
              source_type="excel_import"):
    if expiry_date is None or float(qty) <= 0:
        return

    conn.execute("""
        INSERT INTO inventory_batches (
            item_id, branch_id, quantity, remaining_quantity,
            received_date, expiry_date, unit_cost, source_type
        )
        VALUES (?, ?, ?, ?, CURRENT_DATE, ?, ?, ?)
    """, (
        item_id, branch_id, qty, qty,
        expiry_date, buy_price, source_type
    ))


def excel_template_bytes():
    df = pd.DataFrame([
        {
            "كود الصنف": "1001",
            "اسم الصنف": "مثال قطعة",
            "كود الميزان": "",
            "الوحدة": "قطعة",
            "الكمية": 24,
            "سعر الشراء": 2.5,
            "سعر البيع": 4.0,
            "تاريخ الصلاحية": "",
        },
        {
            "كود الصنف": "2001",
            "اسم الصنف": "مثال بالكيلو",
            "كود الميزان": "90",
            "الوحدة": "كجم",
            "الكمية": 10.5,
            "سعر الشراء": 18.0,
            "سعر البيع": 25.0,
            "تاريخ الصلاحية": date.today(),
        },
    ])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="الأصناف")
        ws = writer.book["الأصناف"]
        widths = [18, 30, 18, 15, 15, 18, 18, 20]
        for i, width in enumerate(widths, 1):
            ws.column_dimensions[chr(64 + i)].width = width

    return output.getvalue()


def get_branches():
    conn = get_db_connection()
    try:
        return conn.execute(
            "SELECT id, branch_name FROM branches ORDER BY branch_name"
        ).fetchall()
    finally:
        conn.close()


def show_page():
    back_button(key="back_items_import")

    st.title("📥 استيراد الأصناف من Excel")
    st.caption("النظام المعتمد: قطعة أو كجم فقط — بدون كراتين أو تحويلات.")

    branches = get_branches()
    if not branches:
        st.warning("لا توجد فروع مسجلة.")
        return

    branch_map = {row["branch_name"]: row["id"] for row in branches}
    all_branches_label = "جميع الفروع (تعريف الأصناف وتحديث بياناتها فقط)"
    branch_name = ui_field(st.selectbox, "items_import:168", "اختر الفرع", [all_branches_label] + list(branch_map.keys()))
    all_branches = branch_name == all_branches_label
    target_branches = list(branch_map.items()) if all_branches else [(branch_name, branch_map[branch_name])]

    st.markdown("### 📄 نموذج Excel")
    st.info(
        "الأعمدة المطلوبة: كود الصنف، اسم الصنف، الوحدة، الكمية، "
        "سعر الشراء، سعر البيع. كود الميزان وتاريخ الصلاحية اختياريان. "
        "الوحدة يجب أن تكون قطعة أو كجم فقط."
    )

    st.download_button(
        "⬇️ تحميل نموذج Excel الجديد",
        excel_template_bytes(),
        "نموذج_استيراد_الأصناف_قطعة_او_كجم.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    if "items_import_mode" not in st.session_state:
        st.session_state["items_import_mode"] = "add"

    st.markdown("### ⚙️ طريقة الاستيراد")
    c1, c2, c3 = st.columns(3)

    if c1.button("➕ إضافة للمخزون", use_container_width=True):
        st.session_state["items_import_mode"] = "add"
        st.rerun()

    if c2.button("💲 تحديث البيانات والأسعار", use_container_width=True):
        st.session_state["items_import_mode"] = "price"
        st.rerun()

    if c3.button("🔄 استبدال الرصيد", use_container_width=True):
        st.session_state["items_import_mode"] = "replace"
        st.rerun()

    mode = st.session_state["items_import_mode"]
    if all_branches:
        st.info("الاستيراد لجميع الفروع يعرّف الأصناف ويحدّث بياناتها فقط، ولا يغيّر كميات المخزون الحالية.")

    if mode == "add":
        st.success("الوضع الحالي: إضافة الكمية الموجودة في الملف إلى الرصيد الحالي.")
    elif mode == "price":
        st.info("الوضع الحالي: تحديث الاسم والوحدة وسعر الشراء وسعر البيع فقط دون تغيير الكمية.")
    else:
        st.warning("الوضع الحالي: استبدال رصيد الصنف بالكمية الموجودة في الملف.")

    uploaded = ui_field(st.file_uploader, "items_import:216", 
        "اختر ملف Excel",
        type=["xlsx"],
        key="items_import_excel"
    )

    if uploaded is None:
        return

    try:
        df = _read_items_excel(uploaded)
    except Exception as exc:
        show_operation_error(exc, announce=True, context='views/items_import.py:228')
        return

    if 'سعر الميزان' in df.columns:
        st.info('سيُحدّث سعر الميزان فقط؛ تُتجاهل بقية بيانات الملف، والخانات الفارغة لا تمسح سعرًا موجودًا.')
        st.dataframe(df,use_container_width=True,hide_index=True)
        if st.button('تحديث سعر الميزان فقط',type='primary',key='import_scale_prices_only'):
            conn=None
            try:
                import os
                rows=df[['كود الصنف','سعر الميزان']].where(df[['كود الصنف','سعر الميزان']].notna(),None).to_dict('records')
                branches_selected=[b for _,b in target_branches]
                if os.name=='nt':
                    from offline_store import _request_with_auth_retry
                    response=_request_with_auth_retry('POST','/items/scale-prices',json={'branch_ids':branches_selected,'rows':rows},timeout=30)
                    response.raise_for_status();result=response.json()
                else:
                    from views.scale_prices import import_prices
                    conn=get_db_connection();result=import_prices(conn,st.session_state.get('user_id'),branches_selected,rows);conn.commit()
                st.success(f"تم تحديث سعر الميزان: {result['updated']}؛ خانات فارغة متروكة: {result['blank_skipped']}")
            except Exception as e:
                if conn:conn.rollback()
                st.error(str(e))
            finally:
                if conn:conn.close()
        return

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        st.error("الأعمدة التالية غير موجودة في الملف: " + "، ".join(missing))
        return

    st.markdown("### 👁️ معاينة")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not st.button("🚀 بدء الاستيراد", type="primary", use_container_width=True):
        return

    conn = get_db_connection()
    imported_count = 0
    new_count = 0
    updated_count = 0
    skipped = []

    try:
        ensure_inventory_batches(conn)


        progress = st.progress(0)
        status = st.empty()
        total = max(len(df) * len(target_branches), 1)
        processed = 0

        for (idx, row), (target_branch_name, branch_id) in (
            (entry, branch) for entry in df.iterrows() for branch in target_branches
        ):
            processed += 1
            effective_mode = "price" if all_branches else mode
            excel_row = idx + 2
            savepoint = f"import_row_{processed}"

            try:
                conn.execute(f"SAVEPOINT {savepoint}")

                code = clean_code(row["كود الصنف"])
                scale_code = clean_code(row.get("كود الميزان", "")) or None
                name = clean_text(row["اسم الصنف"])
                unit_type = clean_unit(row["الوحدة"])
                qty = clean_number(row["الكمية"], 0)
                buy_price = clean_number(row["سعر الشراء"], 0)
                sale_price = clean_number(row["سعر البيع"], 0)
                expiry = clean_expiry(row.get("تاريخ الصلاحية"))

                from views.inventory import assert_barcode_available
                assert_barcode_available(conn,code,name)
                if not code:
                    raise ValueError("كود الصنف فارغ.")
                if not name:
                    raise ValueError("اسم الصنف فارغ.")
                if qty < 0:
                    raise ValueError("الكمية لا يمكن أن تكون سالبة.")
                if buy_price < 0:
                    raise ValueError("سعر الشراء لا يمكن أن يكون سالباً.")
                if sale_price <= 0:
                    raise ValueError("سعر البيع يجب أن يكون أكبر من صفر.")
                if expiry is not None and expiry < date.today():
                    raise ValueError("تاريخ الصلاحية منتهي.")

                existing = conn.execute("""
                    SELECT id, item_code, item_name, quantity, buy_price, avg_cost,
                           sale_price, scale_code, COALESCE(unit_type, 'piece') AS unit_type
                    FROM items
                    WHERE branch_id = ?
                      AND (item_code = ? OR item_name = ?)
                    ORDER BY id
                    LIMIT 1
                    FOR UPDATE
                """, (branch_id, code, name)).fetchone()

                if existing:
                    stored_unit = existing["unit_type"] or "piece"
                    if stored_unit != unit_type:
                        raise ValueError(
                            f"وحدة الصنف الحالية {unit_arabic(stored_unit)} "
                            f"ولا يمكن تغييرها إلى {unit_arabic(unit_type)} من الاستيراد."
                        )

                    item_id = existing["id"]
                    old_qty = float(existing["quantity"] or 0)
                    old_avg = float(existing["avg_cost"] or existing["buy_price"] or 0)

                    if effective_mode == "price":
                        conn.execute("""
                            UPDATE items
                            SET item_code = ?,
                                item_name = ?,
                                buy_price = ?,
                                sale_price = ?,
                                unit_type = ?,
                                scale_code = COALESCE(?, scale_code),
                                pieces_per_carton = 1
                            WHERE id = ?
                        """, (
                            code, name, buy_price, sale_price,
                            unit_type, scale_code, item_id
                        ))

                    elif effective_mode == "replace":
                        conn.execute("""
                            UPDATE items
                            SET item_code = ?,
                                item_name = ?,
                                quantity = ?,
                                buy_price = ?,
                                avg_cost = ?,
                                sale_price = ?,
                                unit_type = ?,
                                scale_code = COALESCE(?, scale_code),
                                pieces_per_carton = 1
                            WHERE id = ?
                        """, (
                            code, name, qty, buy_price, buy_price,
                            sale_price, unit_type, scale_code, item_id
                        ))

                        conn.execute("""
                            DELETE FROM inventory_batches
                            WHERE item_id = ? AND branch_id = ?
                        """, (item_id, branch_id))

                        add_batch(
                            conn, item_id, branch_id, qty,
                            buy_price, expiry, "excel_replace"
                        )

                    else:
                        new_qty = old_qty + qty
                        if new_qty > 0:
                            new_avg = (
                                (old_qty * old_avg) + (qty * buy_price)
                            ) / new_qty
                        else:
                            new_avg = buy_price

                        conn.execute("""
                            UPDATE items
                            SET item_code = ?,
                                item_name = ?,
                                quantity = ?,
                                buy_price = ?,
                                avg_cost = ?,
                                sale_price = ?,
                                unit_type = ?,
                                scale_code = COALESCE(?, scale_code),
                                pieces_per_carton = 1
                            WHERE id = ?
                        """, (
                            code, name, new_qty, buy_price, new_avg,
                            sale_price, unit_type, scale_code, item_id
                        ))

                        add_batch(
                            conn, item_id, branch_id, qty,
                            buy_price, expiry, "excel_add"
                        )

                    updated_count += 1

                else:
                    initial_qty = 0 if effective_mode == "price" else qty

                    row_new = conn.execute("""
                        INSERT INTO items (
                            branch_id, item_code, item_name, quantity,
                            buy_price, avg_cost, sale_price,
                            unit_type, scale_code, pieces_per_carton
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                        RETURNING id
                    """, (
                        branch_id, code, name, initial_qty,
                        buy_price, buy_price, sale_price, unit_type, scale_code
                    )).fetchone()

                    item_id = row_new["id"]

                    if effective_mode != "price":
                        add_batch(
                            conn, item_id, branch_id, qty,
                            buy_price, expiry, "excel_new"
                        )

                    new_count += 1

                imported_count += 1
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")

            except Exception as exc:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                except Exception:
                    pass

                skipped.append({
                    "صف Excel": excel_row,
                    "الفرع": target_branch_name,
                    "كود الصنف": clean_text(row.get("كود الصنف", "")),
                    "اسم الصنف": clean_text(row.get("اسم الصنف", "")),
                    "سبب التخطي": str(exc),
                })

            progress.progress(min(processed / total, 1.0))
            status.write(f"جاري معالجة {processed} من {total} (الفرع: {target_branch_name})")

        conn.commit()
        progress.progress(1.0)
        status.empty()

    except Exception as exc:
        conn.rollback()
        show_operation_error(exc, announce=True, context='views/items_import.py:445')
        return
    finally:
        conn.close()

    notify_success(
        f"✅ انتهى الاستيراد — نجح: {imported_count} | "
        f"جديد: {new_count} | محدث: {updated_count} | "
        f"تم تخطيه: {len(skipped)}",
        reset=imported_count > 0,
    )
    if skipped:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            pd.DataFrame(skipped).to_excel(writer, index=False, sheet_name="Skipped_Rows")
        st.session_state['_operation_success']['report'] = output.getvalue()
    st.rerun()


def _read_items_excel(uploaded):
    """Keep textual identifiers and Excel zero-padding; never rewrite the workbook."""
    import re
    from openpyxl import load_workbook
    from views.inventory import normalize_barcode
    raw=uploaded.getvalue() if hasattr(uploaded,'getvalue') else uploaded.read()
    df=pd.read_excel(io.BytesIO(raw),dtype=object)
    book=load_workbook(io.BytesIO(raw),read_only=True,data_only=True)
    try:
        sheet=book.worksheets[0]
        headers={str(cell.value or '').strip():idx+1 for idx,cell in enumerate(next(sheet.iter_rows(min_row=1,max_row=1)))}
        for name in ('كود الصنف','كود الميزان'):
            if name not in df.columns or name not in headers:continue
            values=[]
            for index in range(len(df)):
                cell=sheet.cell(row=index+2,column=headers[name]);value=cell.value
                if isinstance(value,(int,float)) and abs(value)>=10**15:
                    raise ValueError('باركود Excel الطويل يجب حفظه كنص لتجنب فقد دقة الأرقام.')
                code=normalize_barcode(value)
                if isinstance(value,(int,float)) and not isinstance(value,bool) and re.fullmatch(r'0{2,40}',cell.number_format or ''):
                    code=code.zfill(len(cell.number_format))
                values.append(code)
            df[name]=values
    finally:book.close()
    return df
