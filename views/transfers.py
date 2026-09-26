import streamlit as st
import pandas as pd
import io
from datetime import datetime
from database import get_db_connection

def to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Transfers_Archive')
    return output.getvalue()

def show_page():
    st.header("🔄 نظام تزويد الفروع والمرتجعات والتوالف")
    st.info("💡 إنشاء فاتورة تزويد مجمعة، أو ترحيل المرتجعات والتوالف بين الفروع والمخازن.")

    conn = get_db_connection()
    role = st.session_state.get("role", "")
    user_branch_id = st.session_state.get("branch_id")
    
    if "transfer_cart" not in st.session_state:
        st.session_state["transfer_cart"] = []

    branches = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ يرجى إضافة فروع ومخازن أولاً.")
        conn.close()
        return

    branch_dict = {b["branch_name"]: b["id"] for b in branches}
    
    transfer_mode = st.radio("🎯 اختر القسم:", ["📦 ترحيل بضاعة / توالف جديدة", "📋 أرشيف الحركات السابقة"], horizontal=True)
    st.markdown("---")

    if transfer_mode.startswith("📦"):
        # 🌟 تحديد مصدر الترحيل بناءً على الصلاحيات
        col_from, col_to, col_type = st.columns(3)
        with col_from:
            if role in ["Admin", "General_Supervisor"]:
                from_branch_name = st.selectbox("المصدر (من):", list(branch_dict.keys()))
                from_branch_id = branch_dict[from_branch_name]
            else:
                b_row = conn.execute("SELECT branch_name FROM branches WHERE id=?", (user_branch_id,)).fetchone()
                from_branch_name = b_row["branch_name"] if b_row else "الفرع الحالي"
                from_branch_id = user_branch_id
                st.text_input("المصدر (من):", value=from_branch_name, disabled=True)

        with col_to:
            target_branch_name = st.selectbox("الوجهة المستهدفة (إلى):", [b for b in branch_dict.keys() if branch_dict[b] != from_branch_id])
            target_b_id = branch_dict[target_branch_name]
            
        with col_type:
            # 🌟 إضافة تصنيف الحركة لتمييز التوالف والمرتجعات بوضوح
            transfer_type_option = st.selectbox("نوع الحركة:", ["تزويد بضاعة (إضافة عهدة)", "مرتجعات (رد بضاعة)", "توالف (إعدام أو فحص)"])

        transfer_notes = st.text_input("ملاحظات عامة على الفاتورة (اختياري):", value="")

        st.markdown("### 🛒 إضافة أصناف للحركة")
        items_in_source = conn.execute("SELECT id, item_code, item_name, quantity, sale_price, buy_price FROM items WHERE branch_id = ? AND quantity > 0", (from_branch_id,)).fetchall()

        if items_in_source:
            item_options = {f"{it['item_name']} (المتوفر: {it['quantity']} - السعر: {it['sale_price']} د.ل)": it for it in items_in_source}
            
            with st.form("add_item_to_transfer_cart", clear_on_submit=True):
                col_i1, col_i2, col_i3 = st.columns([2, 1, 1])
                with col_i1:
                    sel_lbl = st.selectbox("اختر الصنف:", list(item_options.keys()))
                with col_i2:
                    selected_data = item_options[sel_lbl]
                    max_q = float(selected_data["quantity"])
                    t_qty = st.number_input("الكمية:", min_value=0.1, max_value=max_q, value=1.0, step=1.0)
                with col_i3:
                    st.write("")
                    st.write("")
                    add_btn = st.form_submit_button("➕ إضافة للسلة", use_container_width=True)
                
                if add_btn:
                    item_obj = item_options[sel_lbl]
                    exists = False
                    for c_it in st.session_state["transfer_cart"]:
                        if c_it["id"] == item_obj["id"]:
                            c_it["qty"] += t_qty
                            exists = True
                            break
                    if not exists:
                        st.session_state["transfer_cart"].append({
                            "id": item_obj["id"], "code": item_obj["item_code"], "name": item_obj["item_name"],
                            "price": float(item_obj["sale_price"]), "buy_price": float(item_obj["buy_price"]), "qty": float(t_qty)
                        })
                    st.success(f"تمت إضافة ({item_obj['item_name']}) بنجاح!")
                    st.rerun()
        else:
            st.warning(f"⚠️ المصدر ({from_branch_name}) خالي من الأصناف حالياً.")

        if st.session_state["transfer_cart"]:
            st.markdown("### 📋 الأصناف المضافة للحركة الحالية")
            for index, c_item in enumerate(st.session_state["transfer_cart"]):
                c_col1, c_col2, c_col3, c_col4, c_col5 = st.columns([1, 2, 1, 1, 0.5])
                c_col1.write(f"🏷️ {c_item['code']}")
                c_col2.write(f"{c_item['name']}")
                c_col3.write(f"الكمية: {c_item['qty']}")
                c_col4.write(f"السعر: {c_item['price']} د.ل")
                if c_col5.button("🗑️", key=f"del_trans_{index}"):
                    st.session_state["transfer_cart"].pop(index)
                    st.rerun()
            
            st.markdown("---")

            col_act1, col_act2 = st.columns(2)
            with col_act1:
                if st.button("🚀 ترحيل واعتماد الحركة", type="primary", use_container_width=True):
                    cur = conn.cursor()
                    try:
                        # 🌟 بناء الفاتورة بتنسيق عمودي صريح لحل مشكلة التلاصق
                        items_summary_list = []
                        for c_item in st.session_state["transfer_cart"]:
                            items_summary_list.append(f"• {c_item['name']} (الكمية: {c_item['qty']})")
                        
                        items_details_str = "\n".join(items_summary_list)
                        if transfer_notes:
                            items_details_str += f"\nملاحظات: {transfer_notes}"

                        for c_item in st.session_state["transfer_cart"]:
                            cur.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))
                            
                            target_item_row = cur.execute("SELECT id FROM items WHERE branch_id = ? AND item_name = ?", (target_b_id, c_item["name"])).fetchone()
                            
                            if target_item_row:
                                cur.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (c_item["qty"], target_item_row["id"]))
                            else:
                                cur.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price) VALUES (?, ?, ?, ?, ?, ?)", 
                                            (target_b_id, c_item["code"], c_item["name"], c_item["qty"], c_item["buy_price"], c_item["price"]))

                        cur.execute("INSERT INTO transfer_logs (from_branch_id, to_branch_id, transfer_type, items_details, status) VALUES (?, ?, ?, ?, ?)", 
                                    (from_branch_id, target_b_id, transfer_type_option, items_details_str, "مع بانتظار تأكيد المستلم"))
                        
                        conn.commit()
                        st.session_state["transfer_cart"] = [] 
                        st.success(f"✅ تم إصدار الحركة ({transfer_type_option}) بنجاح وتم ترحيلها!")
                        st.rerun()
                    except Exception as ex:
                        conn.rollback()
                        st.error(f"❌ حدث خطأ أثناء ترحيل الحركة: {ex}")

            with col_act2:
                if st.button("🗑️ تفريغ السلة بالكامل", use_container_width=True):
                    st.session_state["transfer_cart"] = []
                    st.rerun()

    elif transfer_mode.startswith("📋"):
        st.subheader("📋 أرشيف فواتير وحركات التزويد والتوالف")
        logs_df = pd.read_sql("""
            SELECT transfer_logs.id AS 'رقم الحركة', b1.branch_name AS 'المرسل', b2.branch_name AS 'الفرع المستهدف',
                   transfer_logs.transfer_type AS 'نوع الحركة', transfer_logs.items_details AS 'التفاصيل',
                   transfer_logs.status AS 'الحالة', transfer_logs.transfer_date AS 'التاريخ'
            FROM transfer_logs
            LEFT JOIN branches b1 ON transfer_logs.from_branch_id = b1.id
            LEFT JOIN branches b2 ON transfer_logs.to_branch_id = b2.id
            ORDER BY transfer_logs.id DESC
        """, conn)

        if not logs_df.empty:
            st.dataframe(logs_df, use_container_width=True, hide_index=True)
            st.download_button(label="📥 تصدير الأرشيف", data=to_excel(logs_df), file_name=f"transfers_archive.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        else:
            st.info("📌 لا توجد حركات مسجلة.")

    conn.close()
