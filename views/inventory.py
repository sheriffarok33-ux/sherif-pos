import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("📦 المخزن والتزويد والتحويل (إدارة المخزون والأصناف)")
    st.markdown("""
    > 💡 **إدارة المخزن المركزي:** هذا القسم مخصص بالكامل لتعريف الأصناف، تعديل أسمائها وأسعارها، الاستيراد من إكسيل، تزويد وتحويل الفروع، ومتابعة أرصدة الفروع الأخرى بعيداً عن الفائض والتوالف.
    """)

    conn = get_db_connection()
    
    # جلب كافة الفروع والمخازن
    branches = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ يرجى إضافة فروع أو مخازن أولاً.")
        conn.close()
        return

    branch_dict = {b["branch_name"]: b["id"] for b in branches}
    
    # اختيار الفرع أو المخزن للعرض
    sel_branch_name = st.selectbox("اختر الفرع أو المخزن للعرض والمتابعة:", list(branch_dict.keys()))
    current_b_id = branch_dict[sel_branch_name]

    st.markdown("---")

    # تقسيم الشاشة إلى تبويبات واضحة ومحددة الهدف
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 عرض وتعديل الأرصدة والأسعار", 
        "➕ إضافة صنف جديد (يدوي/باركود)", 
        "📁 الاستيراد والتحديث (Excel)", 
        "🔄 تزويد وتحويل الفروع",
        "🌐 رؤية أرصدة الفروع الأخرى"
    ])

    # --- التبويب الأول: عرض وتعديل الأصناف (الأرصدة، الأسماء، الأسعار، متوسط التكلفة، وهامش الربح) ---
    with tab1:
        st.subheader(f"📋 الأصناف والأرصدة والربحية في: ({sel_branch_name})")
        
        items_df = pd.read_sql("""
            SELECT id, 
                   item_code AS 'كود الصنف', 
                   item_name AS 'اسم الصنف', 
                   quantity AS 'الكمية', 
                   buy_price AS 'سعر الشراء', 
                   sale_price AS 'سعر البيع', 
                   avg_cost AS 'متوسط التكلفة'
            FROM items 
            WHERE branch_id = ?
        """, conn, params=(current_b_id,))

        if not items_df.empty:
            # حساب هامش الربح ونسبة الربح تلقائياً
            items_df['هامش الربح (د.ل)'] = items_df['سعر البيع'] - items_df['متوسط التكلفة']
            items_df['نسبة الربح %'] = ((items_df['هامش الربح (د.ل)'] / items_df['متوسط التكلفة']) * 100).fillna(0).round(1)

            edited_df = st.data_editor(
                items_df, 
                hide_index=True, 
                use_container_width=True,
                key=f"inv_editor_{current_b_id}"
            )

            if st.button("💾 حفظ التعديلات المباشرة (كميات، أسعار، أسماء)", type="primary"):
                cur_up = conn.cursor()
                for _, row in edited_df.iterrows():
                    # تحديث متوسط التكلفة تلقائياً ليساوي سعر الشراء الجديد إذا تم تعديله
                    new_buy = float(row['سعر الشراء'])
                    cur_up.execute("""
                        UPDATE items 
                        SET item_code = ?, item_name = ?, quantity = ?, buy_price = ?, sale_price = ?, avg_cost = ? 
                        WHERE id = ?
                    """, (
                        str(row['كود الصنف']), 
                        str(row['اسم الصنف']), 
                        float(row['الكمية']), 
                        new_buy, 
                        float(row['سعر البيع']), 
                        new_buy, 
                        int(row['id'])
                    ))
                conn.commit()
                st.success("✅ تم تحديث بيانات الأصناف والأسعار ومتوسط التكلفة بنجاح!")
                st.rerun()
        else:
            st.info("لا توجد أصناف مسجلة في هذا الفرع حالياً.")

    # --- التبويب الثاني: إضافة صنف جديد يدوياً مع إمكانية التعميم أو التخصيص ---
    with tab2:
        st.subheader("➕ إضافة صنف جديد (يدعم ماسح الباركود)")
        with st.form("manual_add_item_form", clear_on_submit=True):
            col_1, col_2 = st.columns(2)
            with col_1:
                m_code = st.text_input("كود الصنف / الباركود:")
                m_name = st.text_input("اسم الصنف *:")
                m_qty = st.number_input("الكمية الابتدائية:", min_value=0.0, value=0.0, step=0.5)
            with col_2:
                m_buy = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=0.0, step=0.5)
                m_sale = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=0.0, step=0.5)
                m_expiry = st.text_input("تاريخ الصلاحية (اختياري):", value="")

            st.markdown("---")
            apply_scope = st.radio("🎯 نطاق إضافة الصنف:", ["📍 فرع أو مخزن محدد", "🌐 تعميم لكافة الفروع والمخازن تلقائياً"], horizontal=True, key="add_scope_radio")
            
            target_b_ids = []
            if "فرع أو مخزن محدد" in apply_scope:
                chosen_target_name = st.selectbox("اختر الفرع المستهدف من القائمة:", list(branch_dict.keys()), key="manual_target_branch_select")
                target_b_ids = [branch_dict[chosen_target_name]]
            else:
                target_b_ids = [b["id"] for b in branches]

            submitted_form = st.form_submit_button("💾 حفظ وإضافة الصنف", type="primary", use_container_width=True)

            if submitted_form:
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
                    st.success(f"✅ تم حفظ الصنف ({m_name}) بنجاح وتحديث الأسعار ومتوسط التكلفة!")
                    st.rerun()

    # --- التبويب الثالث: الاستيراد الذكي عبر Excel وتحديث الموجود بدون دوبلكيت ---
    with tab3:
        st.subheader("📁 استيراد وتحديث الأصناف عبر ملف Excel / CSV")
        st.markdown("""
        > 📌 **تنبيه هام:** يجب أن يحتوي الملف على الأعمدة التالية تماماً:  
        > `كود الصنف` | `اسم الصنف` | `سعر البيع` | `سعر الشراء` | `الكمية` | `تاريخ الصلاحية`  
        > *ميزة ذكية:* النظام يبحث بالكود؛ فإذا كان الصنف موجوداً سيقوم **بتحديث بياناته وأسعاره وكميته دون تكرار**، وإذا كان جديداً سيقوم **بإضافته فوراً**.
        """)

        import_scope = st.radio("🎯 نطاق استيراد وتحديث الملف:", ["📍 فرع أو مخزن محدد", "🌐 ترحيل وتحديث لكافة الفروع والمخازن"], horizontal=True, key="imp_scope_radio")
        
        import_target_ids = []
        if "فرع أو مخزن محدد" in import_scope:
            chosen_imp_name = st.selectbox("اختر الفرع المستهدف للاستيراد من القائمة:", list(branch_dict.keys()), key="imp_target_branch_select")
            import_target_ids = [branch_dict[chosen_imp_name]]
        else:
            import_target_ids = [b["id"] for b in branches]

        uploaded_excel = st.file_uploader("اختر ملف Excel أو CSV الخاص بالأصناف", type=["xlsx", "csv"])

        if uploaded_excel is not None:
            try:
                df_imp = pd.read_csv(uploaded_excel) if uploaded_excel.name.endswith('.csv') else pd.read_excel(uploaded_excel)
                st.markdown("### 🔍 معاينة محتوى الملف المرفوع:")
                st.dataframe(df_imp.head(), use_container_width=True)

                if st.button("🚀 تنفيذ الاستيراد والتحديث الذكي", type="primary"):
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
                                # تحديث الموجود (الاسم، الكمية، الأسعار، متوسط التكلفة) بدون دوبلكيت
                                cur_imp.execute("""
                                    UPDATE items SET item_name = ?, quantity = ?, buy_price = ?, sale_price = ?, avg_cost = ?, expiry_date = ?
                                    WHERE id = ?
                                """, (name_val, qty_val, buy_val, sale_val, buy_val, exp_val, chk_item["id"]))
                                updated_count += 1
                            else:
                                # إضافة الجديد
                                cur_imp.execute("""
                                    INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, expiry_date, no_expiry, favorite_rank)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                                """, (b_id, code_val, name_val, qty_val, buy_val, sale_val, buy_val, exp_val))
                                inserted_count += 1

                    conn.commit()
                    st.success(f"✅ تمت العملية بنجاح! تم تحديث ({updated_count}) صنفاً وإضافة ({inserted_count}) صنفاً جديداً بدقة متناهية.")
                    st.rerun()
            except Exception as e:
                st.error(f"خطأ أثناء قراءة الملف: {e}")

    # --- التبويب الرابع: تزويد وتحويل الفروع من المخزن الرئيسي ---
    with tab4:
        st.subheader("🔄 تزويد وتحويل البضاعة بين المخزن والفروع")
        
        main_store_id = next((b["id"] for b in branches if b["branch_type"] == "مخزن"), branches[0]["id"])
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            from_branch_name = st.selectbox("من (المصدر - المخزن):", list(branch_dict.keys()), index=list(branch_dict.values()).index(main_store_id))
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
                with col_add2: transfer_qty = st.number_input("الكمية المراد تحويلها:", min_value=0.01, value=1.0, step=0.5)

                selected_item = item_options[sel_item_str]
                if st.button("➕ إضافة لقائمة التحويل"):
                    if transfer_qty > float(selected_item["quantity"]):
                        st.error("⚠️ الكمية المطلوبة أكبر من المتاح في المخزن المصدر!")
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
                    st.markdown("#### 📋 الأصناف الجاهزة للتحويل:")
                    st.dataframe(pd.DataFrame(st.session_state["transfer_cart"])[["code", "name", "qty"]], use_container_width=True, hide_index=True)
                    
                    col_t1, col_t2 = st.columns(2)
                    with col_t1:
                        if st.button("🚀 اعتماد وتنفيذ التحويل وخصم المخزن", type="primary", use_container_width=True):
                            cur_t = conn.cursor()
                            details_list = []
                            for t_item in st.session_state["transfer_cart"]:
                                # خصم من المصدر
                                cur_t.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (t_item["qty"], t_item["id"]))
                                # إضافة للوجهة أو إنشاؤه إذا لم يكن موجوداً
                                dest_item = cur_t.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (to_b_id, t_item["code"])).fetchone()
                                if dest_item:
                                    cur_t.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (t_item["qty"], dest_item["id"]))
                                else:
                                    cur_t.execute("""
                                        INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, no_expiry, favorite_rank)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)
                                    """, (to_b_id, t_item["code"], t_item["name"], t_item["qty"], t_item["buy_price"], t_item["sale_price"], t_item["buy_price"]))
                                details_list.append(f"{t_item['name']} ({t_item['qty']})")

                            # تسجيل الحركة في السجل
                            cur_t.execute("""
                                INSERT INTO transfer_logs (from_branch_id, to_branch_id, transfer_type, items_details, status)
                                VALUES (?, ?, ?, ?, ?)
                            """, (from_b_id, to_b_id, "تزويد وتحويل", " | ".join(details_list), "بانتظار تأكيد الكاشير"))
                            conn.commit()
                            st.session_state["transfer_cart"] = []
                            st.success("✅ تم تنفيذ التحويل وخصم الكميات وتحديث أرصدة الفروع بنجاح!")
                            st.rerun()
                    with col_t2:
                        if st.button("🗑️ تفريغ القائمة", use_container_width=True):
                            st.session_state["transfer_cart"] = []
                            st.rerun()
            else:
                st.info("لا توجد أصناف متاحة في المخزن المصدر حالياً.")

    # --- التبويب الخامس: رؤية أرصدة الفروع الأخرى ---
    with tab5:
        st.subheader("🌐 رؤية ومتابعة أرصدة الأصناف في باقي الفروع والمخازن")
        all_branches_items = pd.read_sql("""
            b.branch_name AS 'الفرع / المخزن',
            i.item_code AS 'كود الصنف',
            i.item_name AS 'اسم الصنف',
            i.quantity AS 'الكمية المتاحة',
            i.sale_price AS 'سعر البيع'
            FROM items i
            JOIN branches b ON i.branch_id = b.id
            ORDER BY b.id, i.item_name
        """, conn) if False else pd.read_sql("""
            SELECT b.branch_name AS 'الفرع أو المخزن', 
                   i.item_code AS 'كود الصنف', 
                   i.item_name AS 'اسم الصنف', 
                   i.quantity AS 'الكمية المتاحة', 
                   i.sale_price AS 'سعر البيع (د.ل)'
            FROM items i
            JOIN branches b ON i.branch_id = b.id
            ORDER BY b.branch_name, i.item_name
        """, conn)

        if not all_branches_items.empty:
            st.dataframe(all_branches_items, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد بيانات مسجلة للفروع بعد.")

    conn.close()
