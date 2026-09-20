# --- التبويب الثاني: إضافة صنف جديد (مع حل مشكلة الباركود الفوري) ---
    with tab2:
        st.subheader("➕ إضافة صنف جديد (يدعم ماسح الباركود بسلام)")
        st.info("💡 نصيحة: امسح الباركود بالكاميرا أو القارئ في حقل الكود، ثم املأ باقي بيانات الصنف واضغط حفظ.")
        
        # استخدام متغيرات الجلسة (Session State) لمنع ضياع أو مسح الباركود السريع
        if "item_code_input" not in st.session_state: st.session_state["item_code_input"] = ""
        if "item_name_input" not in st.session_state: st.session_state["item_name_input"] = ""

        m_code = st.text_input("كود الصنف / الباركود (امسح هنا أولاً):", key="item_code_input")
        m_name = st.text_input("اسم الصنف *:", key="item_name_input")
        
        col_1, col_2 = st.columns(2)
        with col_1:
            m_qty = st.number_input("الكمية الابتدائية:", min_value=0.0, value=0.0, step=0.5)
            m_buy = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=0.0, step=0.5)
        with col_2:
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

        # زر عادى (خارج الـ Form) عشان لا يحدث أي مسح مفاجئ للبيانات
        if st.button("💾 حفظ وإضافة الصنف الجديد", type="primary", use_container_width=True):
            if not m_name.strip():
                st.warning("⚠️ اسم الصنف حقل إلزامي!")
            elif not m_code.strip():
                st.warning("⚠️ يرجى التأكد من إدخال كود الصنف أو مسح الباركود!")
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
                
                # تفريغ الحقول بعد الحفظ الناجح
                st.session_state["item_code_input"] = ""
                st.session_state["item_name_input"] = ""
                st.success(f"✅ تم حفظ الصنف ({m_name}) بنجاح وتحديث الأسعار ومتوسط التكلفة!")
                st.rerun()

    # --- التبويب الثالث: الاستيراد والتحديث الذكي (تم تغيير الاسم من استيراد إكسيل) ---
    with tab3:
        st.subheader("📁 الاستيراد والتحديث الذكي (Excel / CSV)")
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

                if st.button("🚀 تنفيذ الاستيراد والتحديث الذكي للملف", type="primary"):
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
                    st.success(f"✅ تمت العملية بنجاح! تم تحديث ({updated_count}) صنفاً وإضافة ({inserted_count}) صنفاً جديداً بدقة متناهية.")
                    st.rerun()
            except Exception as e:
                st.error(f"خطأ أثناء قراءة الملف: {e}")
