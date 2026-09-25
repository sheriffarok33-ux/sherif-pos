# ==========================================
    # 2. تعريف وإدارة أصناف المخزن (دعم قارئ الباركود الذكي)
    # ==========================================
    with tab_items:
        branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
        b_dict = {b["branch_name"]: b["id"] for b in branches}
        
        if not b_dict:
            st.warning("⚠️ يرجى إضافة فرع أو مخزن أولاً من تبويب 'إدارة الفروع'.")
        else:
            st.markdown("### 🏷️ إضافة أو بحث عن صنف باستخدام قارئ الباركود")
            selected_branch_name = st.selectbox("اختر الفرع / المخزن:", list(b_dict.keys()), key="item_branch_sel_scan")
            target_branch_id = b_dict[selected_branch_name]
            
            # حقل الباركود المستقل (لا يتأثر بالإنتر السريع لجهاز القارئ)
            scanned_code = st.text_input("قم بمسح الباركود بالقارئ أو اكتب الكود يدوياً:", key="barcode_scanner_input")
            
            # البحث الذكي في قاعدة البيانات عن الكود المقروء
            existing_item = None
            if scanned_code:
                existing_item = conn.execute(
                    "SELECT * FROM items WHERE item_code = ? AND branch_id = ?", 
                    (scanned_code.strip(), target_branch_id)
                ).fetchone()
            
            if existing_item:
                # لو الصنف موجود مسبقاً
                st.success(f"✅ الصنف موجود مسبقاً في المخزن: **{existing_item['item_name']}**")
                st.info(f"الكمية الحالية: {existing_item['quantity']} | سعر البيع: {existing_item['sale_price']} د.ل")
                
                # زر لتعديل الكمية أو السعر سريعاً
                with st.form("update_existing_item_form"):
                    new_qty_add = st.number_input("إضافة كمية جديدة للمخزون:", min_value=0.0, value=0.0, step=1.0)
                    new_price = st.number_input("تعديل سعر البيع:", min_value=0.0, value=float(existing_item['sale_price']), step=0.5)
                    
                    if st.form_submit_button("🔄 تحديث بيانات الصنف", type="primary"):
                        conn.execute(
                            "UPDATE items SET quantity = quantity + ?, sale_price = ? WHERE id = ?",
                            (new_qty_add, new_price, existing_item['id'])
                        )
                        conn.commit()
                        st.success("✅ تم تحديث بيانات الصنف بنجاح!")
                        st.rerun()
            else:
                # لو الصنف جديد تماماً، افتح فورم الإدخال المريح
                if scanned_code:
                    st.warning(f"⚠️ الكود ({scanned_code}) غير مسجل. يرجى إكمال بيانات الصنف الجديد أدناه:")
                
                with st.form("add_new_item_from_scanner", clear_on_submit=True):
                    # نثبت الكود اللي اتقرأ تلقائياً
                    i_code = st.text_input("كود الصنف (الباركود):", value=scanned_code if scanned_code else "")
                    i_name = st.text_input("اسم الصنف (مثل: شوكولاتة / بن / كاجو):")
                    
                    st.markdown("---")
                    st.markdown("#### 📦 تفاصيل الشراء والتكلفة:")
                    unit_type = st.selectbox("كيف تم شراء هذا الصنف؟", ["وحدة / كيلو (مفرد)", "صندوق / كرتونة (تحتوي على قطع)"])
                    
                    col_i3, col_i4, col_i5 = st.columns(3)
                    if unit_type == "صندوق / كرتونة (تحتوي على قطع)":
                        box_count = col_i3.number_input("عدد الصناديق/الكراتين المشتراة:", min_value=0.0, value=1.0, step=1.0)
                        items_per_box = col_i4.number_input("عدد القطع داخل الصندوق الواحد:", min_value=1.0, value=12.0, step=1.0)
                        box_buy_price = col_i5.number_input("سعر شراء الصندوق الإجمالي (د.ل):", min_value=0.0, value=0.0, step=1.0)
                        
                        i_qty = box_count * items_per_box
                        i_buy = box_buy_price / items_per_box if items_per_box > 0 else 0.0
                    else:
                        i_qty = col_i3.number_input("الكمية (بالقطعة أو الكيلو):", min_value=0.0, value=1.0, step=1.0)
                        i_buy = col_i4.number_input("سعر شراء الوحدة/الكيلو (د.ل):", min_value=0.0, value=0.0, step=0.5)
                        col_i5.text_input("ملاحظة:", value="شراء مفرد", disabled=True)

                    st.markdown("---")
                    col_s1, col_s2 = st.columns(2)
                    i_sale = col_s1.number_input("سعر بيع القطعة / الكيلو الواحد (د.ل):", min_value=0.0, value=0.0, step=0.5)
                    i_fav = col_s2.selectbox("إضافة للمفضلة؟", ["لا", "نعم"])
                    
                    uploaded_img = st.file_uploader("صورة الصنف (اختياري):", type=["jpg", "png", "jpeg"])
                    
                    if st.form_submit_button("💾 حفظ الصنف الجديد", type="primary"):
                        if i_code.strip() and i_name.strip():
                            try:
                                fav_val = 1 if i_fav == "نعم" else 0
                                cursor_item = conn.cursor()
                                cursor_item.execute("""
                                    INSERT INTO items (item_code, item_name, branch_id, quantity, buy_price, sale_price, avg_cost, favorite_rank)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                """, (i_code.strip(), i_name.strip(), target_branch_id, i_qty, i_buy, i_sale, i_buy, fav_val))
                                
                                if uploaded_img is not None:
                                    os.makedirs("item_images", exist_ok=True)
                                    img_path = os.path.join("item_images", f"{i_code.strip()}.jpg")
                                    with open(img_path, "wb") as f:
                                        f.write(uploaded_img.getbuffer())
                                        
                                conn.commit()
                                st.success(f"✅ تمت إضافة الصنف ({i_name}) بنجاح!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"⚠️ حدث خطأ: {e}")
                        else:
                            st.warning("⚠️ يرجى إدخال كود الصنف واسمه.")
