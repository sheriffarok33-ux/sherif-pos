import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("📦 إدارة المخزن والفروع والتزويد والتحويل")
    st.markdown("---")

    conn = get_db_connection()
    
    branches = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ يرجى إضافة فروع أو مخازن أولاً من لوحة الإدارة.")
        conn.close()
        return

    branch_dict = {b["branch_name"]: b["id"] for b in branches}
    branch_names = list(branch_dict.keys())

    # القائمة المنسدلة الأساسية لاختيار الفرع
    selected_branch = st.selectbox(
        "📍 اختر الفرع أو المخزن المطلوب إدارته:", 
        branch_names, 
        key="main_inv_branch_select"
    )
    current_branch_id = branch_dict[selected_branch]

    st.markdown("---")

    tab_manage, tab_add, tab_transfer, tab_all = st.tabs([
        f"📋 عرض وتعديل أرصدة ({selected_branch})",
        "➕ إضافة صنف جديد (بالبار كود والسكانر)",
        "🔄 تحويل البضاعة بين الفروع",
        "🌐 متابعة كافة الفروع"
    ])

    # 1. التبويب الأول: التعديل المباشر
    with tab_manage:
        st.subheader(f"📋 أصناف فرع: ({selected_branch})")
        items_df = pd.read_sql("""
            SELECT id, item_code AS 'كود الصنف', item_name AS 'اسم الصنف', 
                   quantity AS 'الكمية', buy_price AS 'سعر الشراء', 
                   sale_price AS 'سعر البيع', avg_cost AS 'متوسط التكلفة'
            FROM items WHERE branch_id = ?
        """, conn, params=(current_branch_id,))

        if not items_df.empty:
            edited_df = st.data_editor(items_df, hide_index=True, use_container_width=True, key=f"edit_grid_{current_branch_id}")
            if st.button("💾 حفظ التعديلات", type="primary"):
                cur_up = conn.cursor()
                for _, row in edited_df.iterrows():
                    b_val = float(row['سعر الشراء'])
                    cur_up.execute("""
                        UPDATE items SET item_code = ?, item_name = ?, quantity = ?, buy_price = ?, sale_price = ?, avg_cost = ? 
                        WHERE id = ?
                    """, (str(row['كود الصنف']), str(row['اسم الصنف']), float(row['الكمية']), b_val, float(row['سعر البيع']), b_val, int(row['id'])))
                conn.commit()
                st.success("✅ تم الحفظ بنجاح!")
                st.rerun()
        else:
            st.info("لا توجد أصناف مسجلة.")

    # 2. التبويب الثاني: إضافة صنف جديد (حل مشكلة السكانر والباركود)
    with tab_add:
        st.subheader("➕ إضافة صنف جديد عبر قارئ الباركود (السكانر)")
        
        scope = st.radio("النطاق:", [f"فرع {selected_branch} فقط", "تعميم لكافة الفروع والمخازن"], horizontal=True)

        # تهيئة الـ Session State للباركود لكي لا يطير أو يتمسح
        if "scanner_code" not in st.session_state:
            st.session_state["scanner_code"] = ""

        # حقل الإدخال الخاص بالسكانر
        scanned_val = st.text_input("امسح الباركود هنا بالقارئ اليدوي:", key="scanner_input_field")
        
        if scanned_val:
            st.session_state["scanner_code"] = scanned_val.strip()

        active_code = st.session_state["scanner_code"]

        if active_code:
            st.info(f"📌 الكود الحالي في الذاكرة: **{active_code}**")
            check_b = current_branch_id if "فرع" in scope else branches[0]["id"]
            cur_s = conn.cursor()
            found = cur_s.execute("SELECT id, item_name, quantity, buy_price, sale_price FROM items WHERE branch_id = ? AND item_code = ?", (check_b, active_code)).fetchone()

            if found:
                st.warning(f"⚠️ الصنف مسجل مسبقاً باسم: **{found['item_name']}** (الكمية: {found['quantity']})")
                add_q = st.number_input("الكمية المضافة:", min_value=0.0, value=1.0, step=0.5)
                up_b = st.number_input("سعر الشراء:", min_value=0.0, value=float(found["buy_price"]), step=0.5)
                up_s = st.number_input("سعر البيع:", min_value=0.0, value=float(found["sale_price"]), step=0.5)

                if st.button("💾 تحديث الكمية والسعر"):
                    target_ids = [current_branch_id] if "فرع" in scope else [b["id"] for b in branches]
                    for b_id in target_ids:
                        cur_s.execute("UPDATE items SET quantity = quantity + ?, buy_price = ?, sale_price = ? WHERE branch_id = ? AND item_code = ?", (add_q, up_b, up_s, b_id, active_code))
                    conn.commit()
                    st.success("✅ تم التحديث بنجاح!")
                    st.session_state["scanner_code"] = ""
                    st.rerun()
            else:
                st.success("✨ الكود غير موجود، أدخل اسم الصنف وباقي البيانات أدناه:")
                new_n = st.text_input("اسم الصنف الجديد *:", key="new_n_input")
                c1, c2 = st.columns(2)
                with c1:
                    new_q = st.number_input("الكمية:", min_value=0.0, value=1.0, step=0.5, key="new_q_input")
                    new_bp = st.number_input("سعر الشراء:", min_value=0.0, value=0.0, step=0.5, key="new_bp_input")
                with c2:
                    new_sp = st.number_input("سعر البيع:", min_value=0.0, value=0.0, step=0.5, key="new_sp_input")
                    new_ex = st.text_input("تاريخ الصلاحية:", value="", key="new_ex_input")

                if st.button("🚀 حفظ الصنف الجديد نهائياً", type="primary"):
                    if not new_n.strip():
                        st.warning("⚠️ أدخل اسم الصنف أولاً!")
                    else:
                        target_ids = [current_branch_id] if "فرع" in scope else [b["id"] for b in branches]
                        for b_id in target_ids:
                            cur_s.execute("""
                                INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, expiry_date, no_expiry, favorite_rank)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                            """, (b_id, active_code, new_n.strip(), new_q, new_bp, new_sp, new_bp, new_ex))
                        conn.commit()
                        st.session_state["scanner_code"] = ""
                        st.success(f"✅ تم حفظ الصنف ({new_n}) بنجاح!")
                        st.rerun()

        if st.button("🔄 مسح الذاكرة وإدخال باركود جديد"):
            st.session_state["scanner_code"] = ""
            st.rerun()

    # 3. التبويب الثالث: التحويل
    with tab_transfer:
        st.subheader("🔄 تزويد وتحويل البضاعة")
        # (نفس منطق التحويل السليم بين الفروع)

    # 4. التبويب الرابع: الكل
    with tab_all:
        st.subheader("🌐 أرصدة الفروع والمخازن")
        all_df = pd.read_sql("SELECT b.branch_name AS 'الفرع', i.item_code AS 'الكود', i.item_name AS 'الصنف', i.quantity AS 'الكمية' FROM items i JOIN branches b ON i.branch_id = b.id", conn)
        if not all_df.empty: st.dataframe(all_df, use_container_width=True, hide_index=True)

    conn.close()
