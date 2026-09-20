import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("📦 إدارة المخزن والفروع والتزويد والاستيراد الذكي")
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

    # تقسيم شاشة المخزن إلى تبويبات شاملة (تم دمج استيراد إكسيل هنا)
    tab_manage, tab_add, tab_excel, tab_transfer, tab_all = st.tabs([
        f"📋 عرض وتعديل أرصدة ({selected_branch})",
        "➕ إضافة صنف جديد (بالبار كود والسكانر)",
        "📁 استيراد وتحديث الأصفار عبر Excel",
        "🔄 تحويل البضاعة بين الفروع",
        "🌐 متابعة كافة الفروع والمخازن"
    ])

    # 1. التبويب الأول: التعديل المباشر
    with tab_manage:
        st.subheader(f"📋 أصناف وأسعار فرع: ({selected_branch})")
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
            st.info("لا توجد أصناف مسجلة في هذا الفرع.")

    # 2. التبويب الثاني: إضافة صنف جديد (مع دعم السكانر والباركود الثابت)
    with tab_add:
        st.subheader("➕ إضافة صنف جديد عبر قارئ الباركود (السكانر)")
        
        scope = st.radio("النطاق:", [f"فرع {selected_branch} فقط", "تعميم لكافة الفروع والمخازن"], horizontal=True)

        if "scanner_code" not in st.session_state:
            st.session_state["scanner_code"] = ""

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
                st.warning(f"⚠️ الصنف مسجل مسبقاً باسم: **{found['item_name']}** (الكمية الحالية: {found['quantity']})")
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

    # 3. التبويب الثالث: استيراد إكسيل الذكي (تم نقله هنا ليقوم بالمهمة بكفاءة)
    with tab_excel:
        st.subheader(f"📁 استيراد ملف الأصناف (Excel / CSV) لـ ({selected_branch})")
        st.markdown("> الأعمدة المطلوبة بالملف: `كود الصنف` | `اسم الصنف` | `سعر البيع` | `سعر الشراء` | `الكمية`")
        
        excel_scope = st.radio("نطاق الاستيراد:", [f"تحديث فرع {selected_branch} فقط", "تحديث وتعميم لكافة الفروع"], horizontal=True)
        uploaded_file = st.file_uploader("اختر ملف إكسيل", type=["xlsx", "csv"], key="inv_excel_uploader")

        if uploaded_file is not None:
            try:
                df_import = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
                st.dataframe(df_import.head(), use_container_width=True)

                if st.button("🚀 تنفيذ استيراد وتحديث الملف", type="primary"):
                    cur_imp = conn.cursor()
                    target_b_ids = [current_branch_id] if "فرع" in excel_scope else [b["id"] for b in branches]
                    
                    up_c, ins_c = 0, 0
                    for _, r in df_import.iterrows():
                        if r.isna().all(): continue
                        c_code = str(r.get("كود الصنف", "")).strip()
                        c_name = str(r.get("اسم الصنف", "")).strip()
                        if not c_name or c_name.lower() == "nan": continue

                        q_val = float(r.get("الكمية", 0.0))
                        b_val = float(r.get("سعر الشراء", 0.0))
                        s_val = float(r.get("سعر البيع", 0.0))

                        for b_id in target_b_ids:
                            chk = cur_imp.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (b_id, c_code)).fetchone()
                            if chk:
                                cur_imp.execute("UPDATE items SET item_name = ?, quantity = ?, buy_price = ?, sale_price = ?, avg_cost = ? WHERE id = ?", (c_name, q_val, b_val, s_val, b_val, chk["id"]))
                                up_c += 1
                            else:
                                cur_imp.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, no_expiry, favorite_rank) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)", (b_id, c_code, c_name, q_val, b_val, s_val, b_val))
                                ins_c += 1
                    conn.commit()
                    st.success(f"✅ تم الاستيراد بنجاح! تحديث ({up_c}) وإضافة ({ins_c}) صنفاً.")
                    st.rerun()
            except Exception as ex:
                st.error(f"خطأ في معالجة الملف: {ex}")

    # 4. التبويب الرابع: التحويل بين الفروع
    with tab_transfer:
        st.subheader("🔄 تحويل البضاعة بين الفروع")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            from_b_name = st.selectbox("من فرع:", branch_names, key="tr_from")
            from_b_id = branch_dict[from_b_name]
        with col_f2:
            to_b_name = st.selectbox("إلى فرع:", branch_names, index=1 if len(branch_names) > 1 else 0, key="tr_to")
            to_b_id = branch_dict[to_b_name]

        if from_b_id == to_b_id:
            st.warning("⚠️ لا يمكن التحويل لنفس الفرع!")
        else:
            if "cart_trans" not in st.session_state: st.session_state["cart_trans"] = []
            src_items = conn.execute("SELECT id, item_code, item_name, quantity, buy_price, sale_price FROM items WHERE branch_id = ?", (from_b_id,)).fetchall()
            if src_items:
                opts = {f"[{it['item_code']}] {it['item_name']} (متاح: {it['quantity']})": it for it in src_items}
                sel_str = st.selectbox("اختر الصنف:", list(opts.keys()))
                qty_val = st.number_input("الكمية المحولة:", min_value=0.01, value=1.0, step=0.5)

                if st.button("➕ إضافة لقائمة التحويل"):
                    item_data = opts[sel_str]
                    if qty_val > float(item_data["quantity"]):
                        st.error("⚠️ الكمية المطلوبة تتجاوز المتاح في الفرع المصدر!")
                    else:
                        st.session_state["cart_trans"].append({
                            "id": item_data["id"], "code": item_data["item_code"],
                            "name": item_data["item_name"], "qty": qty_val,
                            "buy": item_data["buy_price"], "sale": item_data["sale_price"]
                        })
                        st.success("تمت الإضافة بنجاح.")

                if st.session_state["cart_trans"]:
                    st.dataframe(pd.DataFrame(st.session_state["cart_trans"])[["code", "name", "qty"]], use_container_width=True, hide_index=True)
                    if st.button("🚀 اعتماد وترحيل التحويل", type="primary"):
                        cur_t = conn.cursor()
                        for c_row in st.session_state["cart_trans"]:
                            cur_t.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_row["qty"], c_row["id"]))
                            dest_chk = cur_t.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (to_b_id, c_row["code"])).fetchone()
                            if dest_chk:
                                cur_t.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (c_row["qty"], dest_chk["id"]))
                            else:
                                cur_t.execute("INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, no_expiry, favorite_rank) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)", (to_b_id, c_row["code"], c_row["name"], c_row["qty"], c_row["buy"], c_row["sale"], c_row["buy"]))
                        conn.commit()
                        st.session_state["cart_trans"] = []
                        st.success("✅ تمت عملية التحويل بنجاح تام!")
                        st.rerun()
            else:
                st.info("لا توجد أصناف في الفرع المصدر.")

    # 5. التبويب الخامس: المتابعة الشاملة
    with tab_all:
        st.subheader("🌐 أرصدة الفروع والمخازن ككل")
        all_df = pd.read_sql("SELECT b.branch_name AS 'الفرع', i.item_code AS 'الكود', i.item_name AS 'الصنف', i.quantity AS 'الكمية' FROM items i JOIN branches b ON i.branch_id = b.id", conn)
        if not all_df.empty: st.dataframe(all_df, use_container_width=True, hide_index=True)

    conn.close()
