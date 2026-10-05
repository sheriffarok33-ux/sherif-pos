from views.ui_common import back_button
from views.ui_common import item_alerts
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


def _get_main_warehouse(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(branches)").fetchall()}
    if "branch_type" in cols:
        row = conn.execute("""SELECT id,branch_name FROM branches WHERE lower(COALESCE(branch_type,'')) IN ('main','main_warehouse','warehouse','central') OR branch_type LIKE '%رئيس%' OR branch_type LIKE '%مخزن%' ORDER BY id LIMIT 1""").fetchone()
        if row: return row
    return conn.execute("""SELECT id,branch_name FROM branches WHERE branch_name LIKE '%المخزن الرئيسي%' OR branch_name LIKE '%مخزن رئيس%' OR branch_name LIKE '%الرئيسي%' ORDER BY id LIMIT 1""").fetchone()

def _ensure_damaged_stock_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS damaged_stock (id INTEGER PRIMARY KEY AUTOINCREMENT, main_branch_id INTEGER NOT NULL, source_branch_id INTEGER NOT NULL, item_code TEXT, item_name TEXT NOT NULL, quantity REAL NOT NULL DEFAULT 0, damage_type TEXT NOT NULL, notes TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

def _add_saleable_to_main(conn, main_branch_id, source_item, qty):
    code=str(source_item["item_code"] or "").strip()
    target=conn.execute("SELECT id FROM items WHERE branch_id=? AND item_code=? LIMIT 1",(main_branch_id,code)).fetchone() if code else None
    if not target:
        target=conn.execute("SELECT id FROM items WHERE branch_id=? AND item_name=? LIMIT 1",(main_branch_id,source_item["item_name"])).fetchone()
    if target:
        conn.execute("UPDATE items SET quantity=COALESCE(quantity,0)+? WHERE id=?",(qty,target["id"])); return
    cols={r["name"] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    fields=["item_name","branch_id","quantity"]; vals=[source_item["item_name"],main_branch_id,qty]
    for col in ["item_code","buy_price","avg_cost","sale_price"]:
        if col in cols: fields.append(col); vals.append(source_item[col])
    conn.execute(f"INSERT INTO items({','.join(fields)}) VALUES({','.join(['?']*len(fields))})",tuple(vals))


# ============================================================
# تسجيل تلف / مرتجع
# ============================================================

def execute_adjustment(branch_id,item_id,qty,adj_type,notes):
    conn=None
    try:
        conn=get_db_connection()
        item=conn.execute("SELECT id,item_code,item_name,quantity,buy_price,avg_cost,sale_price FROM items WHERE id=? AND branch_id=? FOR UPDATE",(item_id,branch_id)).fetchone()
        if not item: raise ValueError("الصنف غير موجود في الفرع المحدد.")
        qty=float(qty); current=float(item["quantity"] or 0)
        if qty<=0: raise ValueError("الكمية يجب أن تكون أكبر من صفر.")
        main=_get_main_warehouse(conn)
        if not main: raise ValueError("لم يتم العثور على المخزن الرئيسي. تأكد من تعريفه في إدارة الفروع.")
        main_id=int(main["id"]); source_is_main=int(branch_id)==main_id
        unit_cost=float(item["avg_cost"] or item["buy_price"] or 0); total_value=qty*unit_cost
        good=("صالح للبيع" in adj_type or "إعادة صنف تالف/مُصلح" in adj_type)
        bad=("تلف" in adj_type or "هالك" in adj_type or "منتهي" in adj_type or "مرتجع زبون - تالف" in adj_type)
        if not (good or bad): raise ValueError("نوع الحركة غير معروف.")
        if not source_is_main:
            if qty>current: raise ValueError(f"الكمية المطلوبة ({qty}) أكبر من الرصيد المتاح ({current}).")
            conn.execute("UPDATE items SET quantity=quantity-? WHERE id=? AND branch_id=?",(qty,item_id,branch_id))
        if good:
            if source_is_main:
                if "إعادة صنف تالف/مُصلح" in adj_type: conn.execute("UPDATE items SET quantity=quantity+? WHERE id=?",(qty,item_id))
            else: _add_saleable_to_main(conn,main_id,item,qty)
            if "إعادة صنف تالف/مُصلح" in adj_type: db_type="إعادة صنف مُصلح للخدمة"; total_value=-total_value
            else: db_type="مرتجع صالح للبيع"; total_value=0.0
        else:
            if source_is_main:
                if qty>current: raise ValueError(f"الكمية المطلوبة ({qty}) أكبر من الرصيد المتاح ({current}).")
                conn.execute("UPDATE items SET quantity=quantity-? WHERE id=?",(qty,item_id))
            _ensure_damaged_stock_schema(conn)
            db_type="منتهي الصلاحية" if "منتهي" in adj_type else ("مرتجع زبون - تالف" if "مرتجع زبون - تالف" in adj_type else "تالف / هالك")
            conn.execute("INSERT INTO damaged_stock(main_branch_id,source_branch_id,item_code,item_name,quantity,damage_type,notes) VALUES(?,?,?,?,?,?,?)",(main_id,branch_id,item["item_code"],item["item_name"],qty,db_type,notes.strip()))
        movement_notes=(notes.strip()+(" | " if notes.strip() else "")+(f"تحويل إلى {main['branch_name']}" if not source_is_main else "حركة داخل المخزن الرئيسي"))
        conn.execute("INSERT INTO stock_adjustments(branch_id,item_id,item_name,quantity,adjustment_type,loss_or_gain_value,notes) VALUES(?,?,?,?,?,?,?)",(branch_id,item_id,item["item_name"],qty,db_type,total_value,movement_notes))
        conn.commit()
        if source_is_main: msg=f"تم تسجيل {db_type} في المخزن الرئيسي بكمية {qty:,.2f}."
        elif good: msg=f"تم خصم {qty:,.2f} من الفرع وإرجاعها إلى {main['branch_name']} كمخزون صالح."
        else: msg=f"تم خصم {qty:,.2f} من الفرع وإرجاعها إلى {main['branch_name']} كرَصيد تالف/غير صالح للبيع."
        _damages_done(msg)
    except Exception as e:
        if conn:
            try: conn.rollback()
            except Exception: pass
        st.error(f"❌ تعذر تسجيل الحركة: {e}")
    finally:
        if conn: conn.close()


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



@st.dialog("⚠️ مراجعة العملية قبل التنفيذ")
def _stockmove_confirm_dialog():
    pending = st.session_state.get("stockmove_pending_action")
    if not pending:
        return
    st.warning("راجع البيانات جيدًا. لن يتم تنفيذ أي تغيير قبل التأكيد.")
    for label, value in pending.get("summary", []):
        st.write(f"**{label}:** {value}")
    c1, c2 = st.columns(2)
    if c1.button("✅ تأكيد التنفيذ", type="primary", use_container_width=True, key="stockmove_confirm_yes"):
        callback = pending.get("callback")
        args = pending.get("args", [])
        kwargs = pending.get("kwargs", {})
        st.session_state.pop("stockmove_pending_action", None)
        callback(*args, **kwargs)
    if c2.button("❌ إلغاء", use_container_width=True, key="stockmove_confirm_no"):
        st.session_state.pop("stockmove_pending_action", None)
        st.rerun()


def show_page():
    back_button(key="back_damages_returns")
    item_alerts(st.session_state.get("branch_id"), key="alerts_damages_returns")

    if st.session_state.get("stockmove_pending_action"):
        _stockmove_confirm_dialog()
        st.stop()

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

    if not st.session_state.get("damage_returns_entry_lock"):
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
            st.session_state["stockmove_pending_action"] = {
                "callback": execute_adjustment,
                "args": [branch_id, selected["id"], qty, adj_type, notes],
                "summary": [("العملية", adj_type), ("الفرع", branch_name), ("الصنف", selected["item_name"]), ("الكمية", f"{float(qty):,.2f}"), ("السبب", notes or "-")],
            }
            st.rerun()

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
            st.session_state["stockmove_pending_action"] = {
                "callback": execute_adjustment,
                "args": [branch_id, selected["id"], qty, st.session_state["return_kind"], notes],
                "summary": [("العملية", st.session_state["return_kind"]), ("الفرع", branch_name), ("الصنف", selected["item_name"]), ("الكمية", f"{float(qty):,.2f}"), ("ملاحظات", notes or "-")],
            }
            st.rerun()

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
            st.session_state["stockmove_pending_action"] = {
                "callback": execute_surplus,
                "args": [branch_id, selected["id"], qty, notes],
                "summary": [("العملية", "إضافة فائض مخزني"), ("الفرع", branch_name), ("الصنف", selected["item_name"]), ("الكمية", f"{float(qty):,.2f}"), ("السبب", notes or "-")],
            }
            st.rerun()

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
            st.session_state["stockmove_pending_action"] = {
                "callback": execute_price_update,
                "args": [selected["item_code"], selected["item_name"], new_price],
                "summary": [("العملية", "تعديل وتعميم سعر البيع"), ("الصنف", selected["item_name"]), ("السعر الحالي", f"{float(selected['sale_price'] or 0):,.2f} د.ل"), ("السعر الجديد", f"{float(new_price):,.2f} د.ل")],
            }
            st.rerun()

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

