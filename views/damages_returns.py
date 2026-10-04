import streamlit as st
import pandas as pd
import io
from database import get_db_connection


# ============================================================
# أدوات مساعدة
# ============================================================

def get_branches():
    conn = None
    try:
        conn = get_db_connection()

        return conn.execute(
            """
            SELECT id, branch_name
            FROM branches
            ORDER BY id ASC
            """
        ).fetchall()

    finally:
        if conn:
            conn.close()


def get_branch_items(branch_id):
    conn = None
    try:
        conn = get_db_connection()

        return conn.execute(
            """
            SELECT
                id,
                item_code,
                item_name,
                quantity,
                buy_price,
                avg_cost,
                sale_price
            FROM items
            WHERE branch_id = ?
            ORDER BY item_name ASC
            """,
            (branch_id,)
        ).fetchall()

    finally:
        if conn:
            conn.close()


# ============================================================
# تسجيل تلف / مرتجع
# ============================================================

def execute_adjustment(
    branch_id,
    item_id,
    qty,
    adj_type,
    notes
):

    conn = None

    try:
        conn = get_db_connection()

        # قفل الصنف أثناء الحركة
        item = conn.execute(
            """
            SELECT
                id,
                item_name,
                quantity,
                buy_price,
                avg_cost
            FROM items
            WHERE id = ?
            AND branch_id = ?
            FOR UPDATE
            """,
            (item_id, branch_id)
        ).fetchone()

        if not item:
            raise ValueError(
                "الصنف غير موجود في الفرع المحدد."
            )

        current_qty = float(
            item["quantity"] or 0
        )

        avg_cost = float(
            item["avg_cost"] or 0
        )

        buy_price = float(
            item["buy_price"] or 0
        )

        unit_cost = (
            avg_cost
            if avg_cost > 0
            else buy_price
        )

        total_value = (
            float(qty) * unit_cost
        )

        # ----------------------------------------------------
        # مرتجع صالح / إعادة صنف مُصلح
        # ----------------------------------------------------

        if (
            "صالح للبيع" in adj_type
            or "إعادة صنف تالف/مُصلح" in adj_type
        ):

            conn.execute(
                """
                UPDATE items
                SET quantity = quantity + ?
                WHERE id = ?
                AND branch_id = ?
                """,
                (
                    qty,
                    item_id,
                    branch_id
                )
            )

            if "إعادة صنف تالف/مُصلح" in adj_type:

                db_type = (
                    "إعادة صنف مُصلح للخدمة"
                )

                # تخفيض قيمة الخسائر السابقة
                total_value = -total_value

            else:

                db_type = (
                    "مرتجع صالح للبيع"
                )

                # المرتجع الصالح ليس خسارة
                total_value = 0.0

        # ----------------------------------------------------
        # تلف / منتهي / مرتجع تالف
        # ----------------------------------------------------

        elif (
            "تلف" in adj_type
            or "منتهي" in adj_type
            or "مرتجع زبون - تالف" in adj_type
        ):

            if float(qty) > current_qty:

                raise ValueError(
                    f"الكمية المطلوبة ({qty}) "
                    f"أكبر من الرصيد المتاح "
                    f"({current_qty})."
                )

            conn.execute(
                """
                UPDATE items
                SET quantity = quantity - ?
                WHERE id = ?
                AND branch_id = ?
                """,
                (
                    qty,
                    item_id,
                    branch_id
                )
            )

            if "منتهي" in adj_type:

                db_type = (
                    "منتهي الصلاحية"
                )

            elif "مرتجع زبون - تالف" in adj_type:

                db_type = (
                    "مرتجع زبون - تالف"
                )

            else:

                db_type = (
                    "تالف / هالك"
                )

        else:

            raise ValueError(
                "نوع الحركة غير معروف."
            )

        # ----------------------------------------------------
        # تسجيل الحركة
        # ----------------------------------------------------

        conn.execute(
            """
            INSERT INTO stock_adjustments
            (
                branch_id,
                item_id,
                item_name,
                quantity,
                adjustment_type,
                loss_or_gain_value,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                branch_id,
                item_id,
                item["item_name"],
                qty,
                db_type,
                total_value,
                notes.strip()
            )
        )

        conn.commit()

        _damages_done("تم تسجيل الحركة وتحديث المخزون بنجاح.")

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تنفيذ حركة المخزون."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# إضافة فائض
# ============================================================

def execute_surplus(
    branch_id,
    item_id,
    qty,
    notes
):

    conn = None

    try:
        conn = get_db_connection()

        item = conn.execute(
            """
            SELECT
                id,
                item_name,
                quantity
            FROM items
            WHERE id = ?
            AND branch_id = ?
            FOR UPDATE
            """,
            (
                item_id,
                branch_id
            )
        ).fetchone()

        if not item:

            raise ValueError(
                "الصنف غير موجود في الفرع المحدد."
            )

        if float(qty) <= 0:

            raise ValueError(
                "كمية الفائض يجب أن تكون "
                "أكبر من صفر."
            )

        conn.execute(
            """
            UPDATE items
            SET quantity = quantity + ?
            WHERE id = ?
            AND branch_id = ?
            """,
            (
                qty,
                item_id,
                branch_id
            )
        )

        conn.execute(
            """
            INSERT INTO stock_adjustments
            (
                branch_id,
                item_id,
                item_name,
                quantity,
                adjustment_type,
                loss_or_gain_value,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                branch_id,
                item_id,
                item["item_name"],
                qty,
                "فائض مخزني",
                0.0,
                notes.strip()
            )
        )

        conn.commit()

        _damages_done(f"تمت إضافة الفائض ({qty}) للصنف بنجاح.")

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر إضافة الفائض."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# تحديث السعر
# ============================================================

def execute_price_update(
    item_code,
    item_name,
    new_price
):

    conn = None

    try:
        conn = get_db_connection()

        if new_price < 0:

            raise ValueError(
                "السعر لا يمكن أن يكون سالباً."
            )

        # نعتمد على الكود أولاً لأنه الأدق
        if item_code:

            result = conn.execute(
                """
                UPDATE items
                SET sale_price = ?
                WHERE item_code = ?
                """,
                (
                    new_price,
                    item_code
                )
            )

        else:

            # احتياطياً للصنف بدون باركود
            result = conn.execute(
                """
                UPDATE items
                SET sale_price = ?
                WHERE item_name = ?
                """,
                (
                    new_price,
                    item_name
                )
            )

        if result.rowcount == 0:

            raise ValueError(
                "لم يتم العثور على الصنف."
            )

        conn.commit()

        _damages_done(f"تم تحديث وتعميم السعر الجديد ({new_price:.2f} د.ل) بنجاح.")

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر تحديث سعر الصنف."
        )

        st.code(str(e))

    finally:

        if conn:
            conn.close()


# ============================================================
# الصفحة
# ============================================================

def _excel_bytes(df, sheet_name="Movements"):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    return output.getvalue()


def _set_damage_mode(mode):
    st.session_state["damage_returns_mode"] = mode
    st.rerun()


@st.dialog("✅ تمت العملية بنجاح")
def _damages_success_dialog():
    st.success(st.session_state.get("damages_success_message", "تمت العملية بنجاح."))
    if st.button("موافق", type="primary", use_container_width=True, key="damages_success_ok"):
        st.session_state.pop("damages_success_pending", None)
        st.session_state.pop("damages_success_message", None)
        st.rerun()


def _damages_done(message):
    st.session_state["damages_success_message"] = message
    st.session_state["damages_success_pending"] = True
    st.rerun()


def show_page():
    if st.session_state.get("damages_success_pending"):
        _damages_success_dialog()

    st.markdown(
        """
        <style>
        .stDataFrame div, .stDataFrame span, .stDataFrame p,
        div[data-testid="stTable"] *, th, td,
        div[data-baseweb="select"] *, span, p, label, h3, h4 {
            font-family: 'Tajawal', sans-serif !important;
        }
        .rtl-container {direction: rtl !important; text-align: right !important;}
        </style>
        """,
        unsafe_allow_html=True
    )

    st.markdown("## ♻️ حركة وتصحيح المخزون")
    st.caption(
        "التالف، منتهي الصلاحية، المرتجعات، الفائض، تعديل السعر وسجل الحركات "
        "في شاشة واحدة."
    )

    try:
        branches = get_branches()
    except Exception as e:
        st.error("❌ تعذر تحميل الفروع.")
        st.code(str(e))
        return

    if not branches:
        st.warning("⚠️ لا توجد فروع مسجلة في النظام.")
        return

    b_dict = {b["branch_name"]: b["id"] for b in branches}

    if "damage_returns_mode" not in st.session_state:
        st.session_state["damage_returns_mode"] = "adjustment"

    # كل الاختيارات التشغيلية أزرار.
    row1 = st.columns(4)
    if row1[0].button("🗑️ تالف / هالك", use_container_width=True):
        st.session_state["damage_adj_type"] = "🗑️ تلف / كسر (خسارة تشغيلية)"
        _set_damage_mode("adjustment")
    if row1[1].button("📅 منتهي الصلاحية", use_container_width=True):
        st.session_state["damage_adj_type"] = "⏳ منتهي الصلاحية (خسارة تشغيلية)"
        _set_damage_mode("adjustment")
    if row1[2].button("↩️ مرتجع", use_container_width=True):
        _set_damage_mode("return")
    if row1[3].button("➕ فائض مخزني", use_container_width=True):
        _set_damage_mode("surplus")

    row2 = st.columns(3)
    if row2[0].button("💲 تعديل السعر", use_container_width=True):
        _set_damage_mode("price")
    if row2[1].button("📋 سجل الحركات", use_container_width=True):
        _set_damage_mode("log")
    if row2[2].button("📥 تصدير الحركات Excel", use_container_width=True):
        _set_damage_mode("export")

    mode = st.session_state["damage_returns_mode"]
    st.markdown("---")

    # --------------------------------------------------------
    # تلف / منتهي
    # --------------------------------------------------------
    if mode == "adjustment":
        branch_name = st.selectbox(
            "🏢 اختر الفرع / المخزن:",
            list(b_dict.keys()),
            key="damage_branch_btn"
        )
        branch_id = b_dict[branch_name]
        items = get_branch_items(branch_id)
        if not items:
            st.info("لا توجد أصناف في هذا الفرع.")
            return

        opts = {
            f"[{x['item_code'] or 'بدون'}] {x['item_name']} (متاح: {x['quantity']})": x
            for x in items
        }
        selected = opts[st.selectbox("📦 اختر الصنف:", list(opts), key="damage_item_btn")]
        qty = st.number_input("الكمية:", min_value=0.01, value=1.0, step=0.5, key="damage_qty_btn")
        notes = st.text_input("ملاحظات / سبب الحركة:", key="damage_notes_btn")
        adj_type = st.session_state.get(
            "damage_adj_type",
            "🗑️ تلف / كسر (خسارة تشغيلية)"
        )
        st.info(f"نوع الحركة المحدد: **{adj_type}**")

        if st.button("💾 اعتماد الحركة وتحديث المخزون", type="primary", use_container_width=True):
            execute_adjustment(branch_id, selected["id"], qty, adj_type, notes)

    # --------------------------------------------------------
    # المرتجعات - الأنواع نفسها أصبحت أزراراً
    # --------------------------------------------------------
    elif mode == "return":
        if "return_kind" not in st.session_state:
            st.session_state["return_kind"] = "🔄 مرتجع زبون - صالح للبيع (يعود للمخزن)"

        k1, k2, k3 = st.columns(3)
        if k1.button("✅ مرتجع صالح للبيع", use_container_width=True):
            st.session_state["return_kind"] = "🔄 مرتجع زبون - صالح للبيع (يعود للمخزن)"
            st.rerun()
        if k2.button("⚠️ مرتجع تالف", use_container_width=True):
            st.session_state["return_kind"] = "⚠️ مرتجع زبون - تالف (لا يعود للبيع)"
            st.rerun()
        if k3.button("🔧 إعادة صنف مُصلح", use_container_width=True):
            st.session_state["return_kind"] = "🔄 إعادة صنف تالف/مُصلح إلى المخزن (إلغاء إتلاف)"
            st.rerun()

        branch_name = st.selectbox("🏢 اختر الفرع:", list(b_dict), key="return_branch_btn")
        branch_id = b_dict[branch_name]
        items = get_branch_items(branch_id)
        if not items:
            st.info("لا توجد أصناف في هذا الفرع.")
            return
        opts = {
            f"[{x['item_code'] or 'بدون'}] {x['item_name']} (الرصيد: {x['quantity']})": x
            for x in items
        }
        selected = opts[st.selectbox("📦 اختر الصنف:", list(opts), key="return_item_btn")]
        qty = st.number_input("الكمية:", min_value=0.01, value=1.0, step=0.5, key="return_qty_btn")
        notes = st.text_input("ملاحظات:", key="return_notes_btn")
        st.info(f"نوع المرتجع المحدد: **{st.session_state['return_kind']}**")
        if st.button("💾 اعتماد المرتجع", type="primary", use_container_width=True):
            execute_adjustment(
                branch_id, selected["id"], qty,
                st.session_state["return_kind"], notes
            )

    # --------------------------------------------------------
    # فائض
    # --------------------------------------------------------
    elif mode == "surplus":
        branch_name = st.selectbox("🏢 اختر الفرع:", list(b_dict), key="surplus_branch_btn")
        branch_id = b_dict[branch_name]
        items = get_branch_items(branch_id)
        if not items:
            st.info("لا توجد أصناف في هذا الفرع.")
            return
        opts = {
            f"[{x['item_code'] or 'بدون'}] {x['item_name']} (الحالي: {x['quantity']})": x
            for x in items
        }
        selected = opts[st.selectbox("📦 اختر الصنف:", list(opts), key="surplus_item_btn")]
        qty = st.number_input("كمية الفائض:", min_value=0.01, value=1.0, step=0.5, key="surplus_qty_btn")
        notes = st.text_input("سبب الفائض:", value="جرد / فائض مخزني", key="surplus_notes_btn")
        if st.button("💾 اعتماد وإضافة الفائض", type="primary", use_container_width=True):
            execute_surplus(branch_id, selected["id"], qty, notes)

    # --------------------------------------------------------
    # السعر
    # --------------------------------------------------------
    elif mode == "price":
        conn = None
        try:
            conn = get_db_connection()
            rows = conn.execute(
                """
                SELECT DISTINCT item_code, item_name, sale_price
                FROM items
                ORDER BY item_name ASC
                """
            ).fetchall()
        finally:
            if conn:
                conn.close()

        if not rows:
            st.info("لا توجد أصناف مسجلة.")
            return

        opts = {
            f"[{x['item_code'] or 'بدون'}] {x['item_name']} (الحالي: {x['sale_price']} د.ل)": x
            for x in rows
        }
        selected = opts[st.selectbox("📦 اختر الصنف:", list(opts), key="price_item_btn")]
        new_price = st.number_input(
            "سعر البيع الجديد:",
            min_value=0.0,
            value=float(selected["sale_price"] or 0),
            step=0.5,
            key="price_value_btn"
        )
        st.info("سيتم تعميم السعر على الفروع والمخازن لنفس الصنف.")
        if st.button("💾 حفظ وتعميم السعر", type="primary", use_container_width=True):
            execute_price_update(selected["item_code"], selected["item_name"], new_price)

    # --------------------------------------------------------
    # سجل الحركات / التصدير
    # --------------------------------------------------------
    elif mode in ("log", "export"):
        branch_name = st.selectbox(
            "🏢 اختر الفرع لعرض الحركات:",
            list(b_dict),
            key=f"log_branch_{mode}"
        )
        branch_id = b_dict[branch_name]
        conn = None
        try:
            conn = get_db_connection()
            rows = conn.execute(
                """
                SELECT id, item_name, quantity, adjustment_type,
                       loss_or_gain_value, notes, created_at
                FROM stock_adjustments
                WHERE branch_id = ?
                ORDER BY id DESC
                """,
                (branch_id,)
            ).fetchall()
        finally:
            if conn:
                conn.close()

        if not rows:
            st.info("لا توجد حركات مسجلة لهذا الفرع.")
            return

        df = pd.DataFrame([{
            "رقم الحركة": r["id"],
            "اسم الصنف": r["item_name"],
            "الكمية": float(r["quantity"] or 0),
            "نوع الحركة": r["adjustment_type"],
            "قيمة الخسارة/التسوية": float(r["loss_or_gain_value"] or 0),
            "الملاحظات": r["notes"] or "",
            "التاريخ والوقت": r["created_at"],
        } for r in rows])

        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption("يمكن تحديد الخلايا من الجدول ونسخها مباشرة.")

        st.download_button(
            "📥 تنزيل سجل الحركات Excel",
            data=_excel_bytes(df, "Stock_Movements"),
            file_name=f"stock_movements_branch_{branch_id}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )

