import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("📦 الأصناف وتوزيع الفروع والمخازن")
    st.info("💡 إدارة شاملة للأصناف: التعديل المباشر، إدخال الباركود، الاستيراد الذكي (تحديث الموجود ومنع التكرار)، وعمليات تزويد الفروع.")

    conn = get_db_connection()
    
    # جلب الفروع
    branches = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ يرجى إضافة فروع أو مخازن أولاً.")
        conn.close()
        return

    branch_dict = {b["branch_name"]: b["id"] for b in branches}
    
    # اختيار الفرع الحالي للعرض والإدارة العامة
    sel_branch_name = st.selectbox("اختر الفرع أو المخزن الأساسي للعرض:", list(branch_dict.keys()))
    current_b_id = branch_dict[sel_branch_name]

    st.markdown("---")

    # تقسيم الشاشة إلى تبويبات احترافية
    tab1, tab2, tab3, tab4 = st.tabs([
        "📋 عرض وتعديل الأصناف", 
        "➕ صنف جديد (مع الباركود)", 
        "📁 الاستيراد الذكي (Excel)", 
        "🔄 تزويد وتحويل الفروع"
    ])

    # --- التبويب الأول: عرض وتعديل الأصناف وأرصدتها ---
    with tab1:
        st.subheader(f"📋 جدول أصناف وأرصدة: ({sel_branch_name})")
        items_df = pd.read_sql("""
            SELECT id, 
                   item_code AS 'كود الصنف / الباركود', 
                   item_name AS 'اسم الصنف', 
                   quantity AS 'الكمية المتاحة', 
                   buy_price AS 'سعر الشراء', 
                   sale_price AS 'سعر البيع', 
                   avg_cost AS 'متوسط التكلفة'
            FROM items 
            WHERE branch_id = ?
        """, conn, params=(current_b_id,))

        if not items_df.empty:
            items_df['هامش الربح (د.ل)'] = items_df['سعر البيع'] - items_df['متوسط التكلفة']
            items_df['نسبة الربح %'] = ((items_df['هامش الربح (د.ل)'] / items_df['متوسط التكلفة']) * 100).fillna(0).round(1)

            edited_df = st.data_editor(
                items_df, 
                hide_index=True, 
                use_container_width=True,
                key=f"inventory_editor_{current_b_id}"
            )

            if st.button("💾 حفظ التعديلات المباشرة", type="primary"):
                cur_up = conn.cursor()
                for _, row in edited_df.iterrows():
                    cur_up.execute("""
                        UPDATE items 
                        SET item_code = ?, item_name = ?, quantity = ?, buy_price = ?, sale_price = ?, avg_cost = ? 
                        WHERE id = ?
                    """, (
                        str(row['كود الصنف / الباركود']), 
                        str(row['اسم الصنف']), 
                        float(row['الكمية المتاحة']), 
                        float(row['سعر الشراء']), 
                        float(row['سعر البيع']), 
                        float(row['متوسط التكلفة']), 
                        int(row['id'])
                    ))
                conn.commit()
                st.success("✅ تم تحديث بيانات الأصناف بنجاح!")
                st.rerun()
        else:
            st.info("لا توجد أصناف مسجلة في هذا الفرع حالياً.")

    # --- التبويب الثاني: إدخال صنف جديد مع قارئ الباركود ---
    with tab2:
        st.subheader("➕ إدخال صنف جديد (يدعم ماسح الباركود)")
        with st.form("manual_barcode_item_form", clear_on_submit=True):
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                m_code = st.text_input("كود الصنف / الباركود:")
                m_name = st.text_input("اسم الصنف *:")
                m_qty = st.number_input("الكمية الابتدائية:", min_value=0.0, value=0.0, step=0.5)
            with col_b2:
                m_buy = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=0.0, step=0.5)
                m_sale = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=0.0, step=0.5)
                m_expiry = st.text_input("تاريخ الصلاحية (اختياري):", value="")

            apply_scope = st.radio("نطاق تطبيق الأصناف:", ["📍 فرع محدد", "🌐 ترحيل لكافة الفروع والمخازن تلقائياً"], horizontal=True, key="manual_scope_radio")
            
            target_b_ids = []
            if "فرع محدد" in apply_scope:
                chosen_target_name = st.selectbox("اختر الفرع المستهدف:", list(branch_dict.keys()), key="manual_target_branch_select")
                target_b_ids = [branch_dict[chosen_target_name]]
            else:
                target_b_ids = [b["id"] for b in branches]

            submitted_barcode_form = st.form_submit_button("💾 حفظ وإضافة الصنف", type="primary", use_container_width=True)

            if submitted_barcode_form:
                if not m_name.strip():
                    st.warning("⚠️ اسم الصنف حقل إلزامي!")
                else:
                    cur_m = conn.cursor()
                    for b_id in target_b_ids:
                        exists = cur_m.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (b_id, m_code.strip())).fetchone()
                        if exists:
                            cur_m.execute("""
                                UPDATE items SET item_name = ?, quantity = quantity + ?, buy_price = ?, sale_price = ?, avg_cost = ?
                                WHERE id = ?
                            """, (m_name.strip(), m_qty, m_buy, m_sale, m_buy, exists["id"]))
                        else:
                            cur_m.execute("""
                                INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, expiry_date, no_expiry, favorite_rank)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                            """, (b_id, m_code.strip(), m_name.strip(), m_qty, m_buy, m_sale, m_buy, m_expiry))
                    conn.commit()
                    st.success(f"✅ تم حفظ الصنف ({m_name}) بنجاح بدون تكرار!")
                    st.rerun()

    # --- التبويب الثالث: الاستيراد الذكي عبر Excel (تحديث الموجود بدون دوبلكيت) ---
    with tab3:
        st.subheader("📁 استيراد ملف أصناف (Excel / CSV)")
        st.markdown("""
        > 📌 **تنبيه:** يجب أن يحتوي الملف على الأعمدة التالية تماماً: `كود الصنف` | `اسم الصنف` | `سعر البيع` | `سعر الشراء` | `الكمية` | `تاريخ الصلاحية`  
        > *ملاحظة ذكية:* النظام يبحث بالكود؛ فإذا وجد الصنف سيقوم **بتحديثه فقط**، وإذا كان جديداً سيقوم **بإضافته** بدون أي تكرار.
        """)

        import_scope = st.radio("نطاق ترحيل الأصناف:", ["📍 فرع محدد", "🌐 ترحيل لكافة الفروع والمخازن تلقائياً"], horizontal=True, key="imp_scope_radio")
        
        import_target_ids = []
        if "فرع محدد" in import_scope:
            chosen_imp_name = st.selectbox("اختر الفرع المستهدف للاستيراد:", list(branch_dict.keys()), key="imp_target_branch_select")
            import_target_ids = [branch_dict[chosen_imp_name]]
        else:
            import_target_ids = [b["id"] for b in branches]

        uploaded_excel = st.file_uploader("اختر ملف Excel أو CSV", type=["xlsx", "csv"])

        if uploaded_excel is not None:
            try:
                df_imp = pd.read_csv(uploaded_excel) if uploaded_excel.name.endswith('.csv') else pd.read_excel(uploaded_excel)
                st.markdown("### 🔍 معاينة الملف:")
                st.dataframe(df_imp.head(), use_container_width=True)

                if st.button("🚀 تنفيذ الاستيراد الذكي وتحديث البيانات", type="primary"):
                    cur_imp = conn.cursor()
                    updated_count, inserted_count = 0, 0

                    for _, row in df_imp.iterrows():
                        if row.isna().all(): continue
                        code_val = str(row.get("كود الصنف", "")).strip()
                        name_val = str(row.get("اسم الصنف", "")).strip()
                        if name_val.lower() in ["nan", "none", ""]: continue

                        qty_val = float(row.get("الكمية", 0.0))
                        buy_val = float(row.get("سعر الشراء", 0.0))
                        sale_val = float(row.get("سعر البيع", 0.0))
                        exp_val = str(row.get("تاريخ الصلاحية", "")).strip()

                        for b_id in import_target_ids:
                            chk_item = cur_imp.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (b_id, code_val)).fetchone()
                            if chk_item:
                                cur_imp.execute("""
                                    UPDATE items SET item_name = ?, quantity = ?, buy_price = ?, sale_price = ?, avg_cost = ?, expiry_date = ?
                                    WHERE id = ?
                                """, (name_val, qty_val, buy_val, sale_val, buy_val, exp_val, chk_item["id"]))
                                updated_count += 1
                            else:
                                cur_imp.execute("""
                                    INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, expiry_date, no_expiry, favorite_rank)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                                """, (b_id, code_val, name_val, qty_val, buy_val, sale_val, buy_val, exp_val))
                                inserted_count += 1

                    conn.commit()
                    st.success(f"✅ تمت العملية بنجاح! تم تحديث ({updated_count}) صنفاً وإضافة ({inserted_count}) صنفاً جديداً بدون أي تكرار.")
                    st.rerun()
            except Exception as e:
                st.error(f"خطأ أثناء قراءة الملف: {e}")

    # --- التبويب الرابع: تزويد وتحويل الفروع ---
    with tab4:
        st.subheader("🔄 تزويد وتحويل الفروع من المخزن الرئيسي")
        
        main_store_id = next((b["id"] for b in branches if b["branch_type"] == "مخزن"), branches[0]["id"])
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            from_branch_name = st.selectbox("من (المصدر):", list(branch_dict.keys()), index=list(branch_dict.values()).index(main_store_id))
            from_b_id = branch_dict[from_branch_name]
        with col_s2:
            to_branch_name = st.selectbox("إلى (الفرع المستهدف):", list(branch_dict.keys()), index=1 if len(branch_dict) > 1 else 0)
            to_b_id = branch_dict[to_branch_name]

        if from_b_id == to_b_id:
            st.warning("⚠️ لا يمكن التحويل لنفس الفرع!")
        else:
            if "transfer_cart" not in st.session_state: st.session_state["transfer_cart"] = []

            source_items = conn.execute("SELECT id, item_code, item_name, quantity, buy_price, sale_price FROM items WHERE branch_id = ?", (from_b_id,)).fetchall()
            if source_items:
                item_options = {f"[{it['item_code']}] {it['item_name']} (المتاح بالمخزن: {it['quantity']})": it for it in source_items}
                
                col_add1, col_add2 = st.columns([2, 1])
                with col_add1: sel_item_str = st.selectbox("اختر الصنف للتحويل:", list(item_options.keys()))
                with col_add2: transfer_qty = st.number_input("الكمية:", min_value=0.01, value=1.0, step=0.5)

                selected_item = item_options[sel_item_str]
                if st.button("➕ إضافة لقائمة التحويل"):
                    if transfer_qty > float(selected_item["quantity"]):
                        st.error("⚠️ الكمية المطلوبة أكبر من المتاح بالمخزن!")
                    else:
                        exists = False
                        for c in st.session_state["transfer_cart"]:
                            if c["id"] == selected_item["id"]:
                                c["qty"] += transfer_qty
                                exists = True
                                break
                        if not exists:
                            st.session_state["transfer_cart"].append({
                                "id": selected_item["id"], "code": selected_item["item_code"],
                                "name": selected_item["item_name"], "qty": transfer_qty,
                                "buy_price": selected_item["buy_price"], "sale_price": selected_item["sale_price"]
                            })
                        st.success("تمت الإضافة لقائمة التحويل بنجاح.")

                if st.session_state["transfer_cart"]:
                    st.dataframe(pd.DataFrame(st.session_state["transfer_cart"])[["code", "name", "qty"]], use_container_width=True, hide_index=True)
                    
                    if st.button("🚀 اعتماد وتنفيذ التحويل وخصم المخزن", type="primary"):
                        cur_t = conn.cursor()
                        details_list = []
                        for t_item in st.session_state["transfer_cart"]:
                            cur_t.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (t_item["qty"], t_item["id"]))
                            dest_item = cur_t.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (to_b_id, t_item["code"])).fetchone()
                            if dest_item:
                                cur_t.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (t_item["qty"], dest_item["id"]))
                            else:
                                cur_t.execute("""
                                    INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, no_expiry, favorite_rank)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)
                                """, (to_b_id, t_item["code"], t_item["name"], t_item["qty"], t_item["buy_price"], t_item["sale_price"], t_item["buy_price"]))
                            details_list.append(f"{t_item['name']} ({t_item['qty']})")

                        cur_t.execute("""
                            INSERT INTO transfer_logs (from_branch_id, to_branch_id, transfer_type, items_details, status)
                            VALUES (?, ?, ?, ?, ?)
                        """, (from_b_id, to_b_id, "تزويد فرع", " | ".join(details_list), "مكتملة"))
                        conn.commit()
                        st.session_state["transfer_cart"] = []
                        st.success("✅ تم تنفيذ التحويل وتحديث الأرصدة بنجاح!")
                        st.rerun()

                    if st.button("🗑️ تفريغ القائمة"):
                        st.session_state["transfer_cart"] = []
                        st.rerun()
            else:
                st.info("لا توجد أصناف في المخزن المصدر حالياً.")

    conn.close()
