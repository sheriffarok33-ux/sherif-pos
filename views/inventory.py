import streamlit as st
import pandas as pd
from datetime import date
from database import get_db_connection


def ensure_inventory_columns():
    conn = None
    try:
        conn = get_db_connection()
        conn.execute(
            """
            ALTER TABLE items
            ADD COLUMN IF NOT EXISTS unit_type TEXT DEFAULT 'piece'
            """
        )
        conn.execute(
            """
            ALTER TABLE items
            ADD COLUMN IF NOT EXISTS pieces_per_carton INTEGER DEFAULT 1
            """
        )
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
                "قطع/كرتون": (
                    int(row["pieces_per_carton"] or 1)
                    if unit_type == "piece" else "-"
                ),
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

        if stored_type == "piece" and pieces_per_carton:
            conn.execute(
                """
                UPDATE items
                SET quantity = ?, buy_price = ?, avg_cost = ?,
                    pieces_per_carton = ?
                WHERE id = ? AND branch_id = ?
                """,
                (
                    new_qty, unit_buy_price, new_avg,
                    int(pieces_per_carton), item_id, branch_id
                )
            )
        else:
            conn.execute(
                """
                UPDATE items
                SET quantity = ?, buy_price = ?, avg_cost = ?
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
        st.success(
            f"✅ تمت إضافة {added_quantity:,.3f} {label} إلى "
            f"({existing['item_name']}). الرصيد الجديد: "
            f"{new_qty:,.3f} {label}."
        )
        st.rerun()
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
                unit_type, int(pieces_per_carton or 1)
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
        st.success(
            f"✅ تم إنشاء الصنف ({item_name}) برصيد أولي "
            f"{initial_quantity:,.3f} {label}."
        )
        st.rerun()
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
    pieces_per_carton = c1.number_input(
        "عدد القطع داخل الكرتون:",
        min_value=1, value=max(1, int(default_pieces or 1)), step=1,
        key=f"{prefix}_pieces_per_carton"
    )
    cartons = c2.number_input(
        "عدد الكراتين المضافة:",
        min_value=0.0, value=1.0, step=1.0,
        key=f"{prefix}_cartons"
    )
    box_price = st.number_input(
        "سعر شراء الكرتون بالكامل (د.ل):",
        min_value=0.0, value=0.0, step=0.5, format="%.2f",
        key=f"{prefix}_box_price"
    )
    qty = float(cartons) * int(pieces_per_carton)
    unit_cost = (
        float(box_price) / int(pieces_per_carton)
        if pieces_per_carton else 0.0
    )
    st.info(
        f"📊 سيتم إضافة **{qty:,.0f} قطعة** | "
        f"تكلفة القطعة **{unit_cost:,.2f} د.ل**"
    )
    return qty, unit_cost, int(pieces_per_carton)


def weight_input_fields(prefix):
    mode = st.radio(
        "طريقة إدخال الوزن:",
        ["⚖️ بالكيلو", "⚖️ بالجرام"],
        horizontal=True,
        key=f"{prefix}_weight_mode"
    )
    if mode == "⚖️ بالكيلو":
        c1, c2 = st.columns(2)
        qty = c1.number_input(
            "الوزن المضاف (كجم):", min_value=0.001,
            value=1.000, step=0.100, format="%.3f",
            key=f"{prefix}_kg"
        )
        cost = c2.number_input(
            "سعر شراء الكيلو (د.ل):", min_value=0.0,
            value=0.0, step=0.5, format="%.2f",
            key=f"{prefix}_kg_cost"
        )
        st.info(
            f"⚖️ سيتم إضافة **{float(qty):,.3f} كجم** | "
            f"قيمة الشراء **{float(qty)*float(cost):,.2f} د.ل**"
        )
        return float(qty), float(cost)

    c1, c2 = st.columns(2)
    grams = c1.number_input(
        "الوزن المضاف (جرام):", min_value=1.0,
        value=1000.0, step=50.0, format="%.0f",
        key=f"{prefix}_grams"
    )
    total = c2.number_input(
        "إجمالي سعر شراء هذه الكمية (د.ل):", min_value=0.0,
        value=0.0, step=0.5, format="%.2f",
        key=f"{prefix}_grams_total"
    )
    qty = float(grams) / 1000.0
    cost = float(total) / qty if qty > 0 else 0.0
    st.info(
        f"⚖️ {grams:,.0f} جرام = **{qty:,.3f} كجم** | "
        f"تكلفة الكيلو **{cost:,.2f} د.ل**"
    )
    return qty, cost


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
        st.success("✅ تم تحديث وحدة الصنف.")
        st.rerun()
    except Exception as e:
        if conn:
            conn.rollback()
        st.error("تعذر تحديث وحدة الصنف.")
        st.code(str(e))
    finally:
        if conn:
            conn.close()


def show_page():
    try:
        ensure_inventory_columns()
    except Exception as e:
        st.error("❌ تعذر تجهيز حقول وحدات المخزون.")
        st.code(str(e))
        return

    st.markdown("## 📦 إدارة المخزن - الأصناف والكميات والباركود")
    st.caption(
        "كل صنف يُحفظ بوحدته الأساسية: قطعة أو كجم. "
        "الجرام يتحول إلى كجم داخلياً."
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
        "اختر المخزن أو الفرع الحالي:", list(b_dict.keys())
    )
    branch_id = b_dict[selected_branch]

    try:
        existing_items = get_branch_items_rows(branch_id)
    except Exception as e:
        st.error("❌ تعذر تحميل أصناف الفرع.")
        st.code(str(e))
        existing_items = []

    operation = st.radio(
        "ماذا تريد أن تفعل؟",
        ["📦 إضافة كمية لصنف موجود", "➕ إنشاء صنف جديد"],
        horizontal=True
    )
    st.markdown("---")

    if operation == "📦 إضافة كمية لصنف موجود":
        st.markdown("### 📦 إضافة مخزون لصنف مسجل")
        if not existing_items:
            st.info("لا توجد أصناف في هذا الفرع حتى الآن.")
        else:
            item_map = {}
            for item in existing_items:
                unit = "كجم" if item["unit_type"] == "kg" else "قطعة"
                label = (
                    f"{item['item_name']} — {item['item_code']} — "
                    f"الرصيد: {float(item['quantity'] or 0):,.3f} {unit}"
                )
                item_map[label] = item

            selected = item_map[
                st.selectbox("اختر الصنف:", list(item_map.keys()))
            ]
            unit_type = selected["unit_type"] or "piece"
            unit_label = "كجم" if unit_type == "kg" else "قطعة"

            c1, c2, c3 = st.columns(3)
            c1.metric(
                "الرصيد الحالي",
                f"{float(selected['quantity'] or 0):,.3f} {unit_label}"
            )
            c2.metric(
                "متوسط التكلفة",
                f"{float(selected['avg_cost'] or 0):,.2f} د.ل/{unit_label}"
            )
            c3.metric(
                "سعر البيع الحالي",
                f"{float(selected['sale_price'] or 0):,.2f} د.ل/{unit_label}"
            )

            # أداة تصحيح لمرة واحدة للأصناف القديمة.
            st.markdown("#### 🛠️ تصحيح وحدة صنف قديم")
            st.caption(
                "استخدم هذا الجزء فقط إذا كانت وحدة الصنف القديمة "
                "مسجلة بشكل غير صحيح."
            )

            legacy_box = st.container(border=True)
            with legacy_box:
                corrected = st.selectbox(
                    "الوحدة الصحيحة:",
                    ["قطعة", "كجم"],
                    index=1 if unit_type == "kg" else 0,
                    key=f"legacy_unit_{selected['id']}"
                )

                legacy_ppc = 1
                if corrected == "قطعة":
                    legacy_ppc = st.number_input(
                        "عدد القطع في الكرتون:",
                        min_value=1,
                        value=max(
                            1,
                            int(selected["pieces_per_carton"] or 1)
                        ),
                        step=1,
                        key=f"legacy_ppc_{selected['id']}"
                    )

                if st.button(
                    "💾 حفظ تصحيح الوحدة",
                    key=f"save_legacy_unit_{selected['id']}"
                ):
                    change_legacy_unit(
                        selected["id"],
                        branch_id,
                        "kg" if corrected == "كجم" else "piece",
                        legacy_ppc
                    )

            with st.form("add_existing_stock_form", clear_on_submit=True):
                if unit_type == "piece":
                    added_qty, unit_cost, ppc = piece_input_fields(
                        "existing",
                        selected["pieces_per_carton"]
                    )
                else:
                    added_qty, unit_cost = weight_input_fields("existing")
                    ppc = 1

                st.markdown("#### 📅 صلاحية الدفعة الجديدة")
                expiry_mode = st.radio(
                    "هل لهذه الدفعة تاريخ انتهاء؟",
                    ["بدون تاريخ انتهاء", "تحديد تاريخ انتهاء"],
                    horizontal=True,
                    key="existing_expiry_mode"
                )

                expiry_date = None
                if expiry_mode == "تحديد تاريخ انتهاء":
                    expiry_date = st.date_input(
                        "تاريخ انتهاء الصلاحية:",
                        value=date.today(),
                        min_value=date.today(),
                        key="existing_expiry_date"
                    )

                submit = st.form_submit_button(
                    "➕ إضافة الكمية للصنف",
                    type="primary",
                    use_container_width=True
                )

            if submit:
                add_stock_to_existing_item(
                    branch_id, selected["id"], added_qty,
                    unit_cost, unit_type, ppc, expiry_date
                )

    else:
        st.markdown("### ➕ إنشاء صنف جديد لأول مرة")
        with st.form("create_new_item_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            item_code = c1.text_input("كود الصنف / الباركود:")
            item_name = c2.text_input("اسم الصنف:")

            unit_choice = st.radio(
                "الوحدة الأساسية للصنف:",
                ["📦 قطعة / كرتون", "⚖️ وزن (كجم / جرام)"],
                horizontal=True
            )

            if unit_choice == "📦 قطعة / كرتون":
                unit_type = "piece"
                qty, cost, ppc = piece_input_fields("new", 1)
                sale_label = "سعر بيع القطعة (د.ل):"
            else:
                unit_type = "kg"
                qty, cost = weight_input_fields("new")
                ppc = 1
                sale_label = "سعر بيع الكيلو (د.ل):"

            st.markdown("#### 📅 صلاحية الرصيد الأولي")
            expiry_mode_new = st.radio(
                "هل لهذا الرصيد تاريخ انتهاء؟",
                ["بدون تاريخ انتهاء", "تحديد تاريخ انتهاء"],
                horizontal=True,
                key="new_expiry_mode"
            )

            expiry_date_new = None
            if expiry_mode_new == "تحديد تاريخ انتهاء":
                expiry_date_new = st.date_input(
                    "تاريخ انتهاء الصلاحية:",
                    value=date.today(),
                    min_value=date.today(),
                    key="new_expiry_date"
                )

            sale_price = st.number_input(
                sale_label, min_value=0.0, value=0.0,
                step=0.5, format="%.2f", key="new_sale_price"
            )

            submit_new = st.form_submit_button(
                "💾 إنشاء الصنف وحفظ الرصيد",
                type="primary",
                use_container_width=True
            )

        if submit_new:
            create_new_inventory_item(
                branch_id, item_code, item_name, qty,
                cost, sale_price, unit_type, ppc,
                expiry_date_new
            )

    st.markdown("---")
    st.markdown("### 📋 جدول الأصناف المسجلة في هذا المخزن")

    try:
        df = get_branch_items(branch_id)
    except Exception as e:
        st.error("❌ تعذر تحميل أصناف المخزن.")
        st.code(str(e))
        df = pd.DataFrame()

    if not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد أصناف مسجلة في هذا المخزن حتى الآن.")

    st.markdown("### 📅 دفعات الصلاحية المسجلة")

    conn = None
    try:
        conn = get_db_connection()
        batch_rows = conn.execute(
            """
            SELECT
                i.item_code,
                i.item_name,
                b.received_date,
                b.expiry_date,
                b.quantity,
                b.remaining_quantity,
                b.source_type
            FROM inventory_batches b
            JOIN items i ON i.id = b.item_id
            WHERE b.branch_id = ?
              AND b.expiry_date IS NOT NULL
            ORDER BY b.expiry_date ASC, i.item_name ASC
            """,
            (branch_id,)
        ).fetchall()

        if batch_rows:
            batch_data = []
            today = date.today()

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
                    "الكود": row["item_code"],
                    "اسم الصنف": row["item_name"],
                    "تاريخ الدخول": row["received_date"],
                    "تاريخ الانتهاء": row["expiry_date"],
                    "كمية الدفعة": float(row["quantity"] or 0),
                    "المتبقي": float(row["remaining_quantity"] or 0),
                    "الحالة": status,
                    "المصدر": (
                        "مشتريات"
                        if row["source_type"] == "purchase"
                        else "إضافة مخزون"
                    ),
                })

            st.dataframe(
                pd.DataFrame(batch_data),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info(
                "لا توجد دفعات لها تاريخ انتهاء مسجلة في هذا الفرع."
            )

    except Exception as e:
        st.error("❌ تعذر تحميل دفعات الصلاحية.")
        st.code(str(e))
    finally:
        if conn:
            conn.close()
