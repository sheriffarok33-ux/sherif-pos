# --- التبويب الثاني: إضافة صنف جديد (منطق الباركود الذكي والـ Enter) ---
    with tab2:
        st.subheader("➕ إضافة صنف جديد عبر الباركود")
        st.info("💡 امسح الباركود بالماسح الضوئي في الحقل بالأسفل واضغط Enter أو اترك الحقل ليتحقق منه النظام تلقائياً.")

        # تهيئة حالة الجلسة للباركود والبيانات
        if "scanned_code" not in st.session_state: st.session_state["scanned_code"] = ""
        if "new_item_name" not in st.session_state: st.session_state["new_item_name"] = ""

        # حقل إدخال الباركود الأساسي
        scanned_input = st.text_input("كود الصنف / الباركود (امسح هنا):", key="barcode_scan_field")

        if scanned_input:
            st.session_state["scanned_code"] = scanned_input.strip()

        # التحقق مما إذا كان الكود موجوداً مسبقاً في قاعدة البيانات للفرع الحالي
        current_scanned_code = st.session_state["scanned_code"]
        
        if current_scanned_code:
            cur_chk = conn.cursor()
            existing_item = cur_chk.execute(
                "SELECT id, item_name, quantity, buy_price, sale_price FROM items WHERE branch_id = ? AND item_code = ?", 
                (current_b_id, current_scanned_code)
            ).fetchone()

            if existing_item:
                st.warning(f"⚠️ هذا الصنف موجود مسبقاً باسم: **{existing_item['item_name']}** (الكمية الحالية: {existing_item['quantity']})")
                st.markdown("يمكنك تعديل الكمية أو الأسعار مباشرة أدناه لتحديثه:")
                
                up_qty = st.number_input("الكمية المضافة / الجديدة:", min_value=0.0, value=0.0, step=0.5, key="up_exist_qty")
                up_buy = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=float(existing_item["buy_price"]), step=0.5, key="up_exist_buy")
                up_sale = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=float(existing_item["sale_price"]), step=0.5, key="up_exist_sale")

                if st.button("💾 تحديث بيانات الصنف الموجود", type="primary"):
                    cur_chk.execute("""
                        UPDATE items 
                        SET quantity = quantity + ?, buy_price = ?, sale_price = ?, avg_cost = ?
                        WHERE branch_id = ? AND item_code = ?
                    """, (up_qty, up_buy, up_sale, up_buy, current_b_id, current_scanned_code))
                    conn.commit()
                    st.success("✅ تم تحديث الصنف بنجاح!")
                    st.session_state["scanned_code"] = ""
                    st.rerun()
            else:
                st.success(f"✨ الكود ({current_scanned_code}) غير موجود. جاري فتح استمارة إدخال الصنف الجديد...")

                # حقول إدخال باقي بيانات الصنف الجديد لأن الكود غير موجود
                new_name = st.text_input("اسم الصنف الجديد *:", key="new_item_name_field")
                
                col_n1, col_n2 = st.columns(2)
                with col_n1:
                    new_qty = st.number_input("الكمية الابتدائية:", min_value=0.0, value=1.0, step=0.5, key="new_item_qty")
                    new_buy = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=0.0, step=0.5, key="new_item_buy")
                with col_n2:
                    new_sale = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=0.0, step=0.5, key="new_item_sale")
                    new_expiry = st.text_input("تاريخ الصلاحية (اختياري):", value="", key="new_item_expiry")

                st.markdown("---")
                apply_scope_new = st.radio("🎯 نطاق حفظ الصنف الجديد:", ["📍 الفرع الحالي فقط", "🌐 تعميم لكافة الفروع والمخازن"], horizontal=True, key="new_item_scope")

                if st.button("🚀 حفظ الصنف الجديد نهائياً", type="primary", use_container_width=True):
                    if not new_name.strip():
                        st.warning("⚠️ يرجى كتابة اسم الصنف أولاً!")
                    else:
                        cur_ins = conn.cursor()
                        target_b_ids = [b["id"] for b in branches] if "كافة الفروع" in apply_scope_new else [current_b_id]
                        
                        for b_id in target_b_ids:
                            # التأكد مرة أخرى لعدم التكرار
                            chk_dupl = cur_ins.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (b_id, current_scanned_code)).fetchone()
                            if chk_dupl:
                                cur_ins.execute("""
                                    UPDATE items SET item_name = ?, quantity = quantity + ?, buy_price = ?, sale_price = ?, avg_cost = ?
                                    WHERE id = ?
                                """, (new_name.strip(), new_qty, new_buy, new_sale, new_buy, chk_dupl["id"]))
                            else:
                                cur_ins.execute("""
                                    INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, expiry_date, no_expiry, favorite_rank)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                                """, (b_id, current_scanned_code, new_name.strip(), new_qty, new_buy, new_sale, new_buy, new_expiry))
                        
                        conn.commit()
                        st.session_state["scanned_code"] = ""
                        st.success(f"✅ تم إضافة وحفظ الصنف ({new_name}) بنجاح تام وبدون أي مسح أو ضياع للكود!")
                        st.rerun()

        if st.button("🔄 مسح الكود وإدخال صنف جديد آخر"):
            st.session_state["scanned_code"] = ""
            st.rerun()
