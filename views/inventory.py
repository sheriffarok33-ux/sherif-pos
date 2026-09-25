# ==========================================
    # 2. تعريف وإدارة أصناف المخزن (شراء كراتين - بيع مفرد)
    # ==========================================
    with tab_items:
        branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
        b_dict = {b["branch_name"]: b["id"] for b in branches}
        
        if not b_dict:
            st.warning("⚠️ يرجى إضافة فرع أو مخزن أولاً من تبويب 'إدارة الفروع'.")
        else:
            st.markdown("### 🏷️ إضافة صنف جديد للمخزن")
            selected_branch_name = st.selectbox("اختر الفرع / المخزن لإضافة الصنف إليه:", list(b_dict.keys()), key="item_branch_sel")
            target_branch_id = b_dict[selected_branch_name]
            
            with st.form("add_item_retail_form", clear_on_submit=True):
                col_i1, col_i2 = st.columns(2)
                i_code = col_i1.text_input("كود الصنف (الباركود):")
                i_name = col_i2.text_input("اسم الصنف (مثل: شوكولاتة / بن / كاجو):")
                
                st.markdown("---")
                st.markdown("#### 📦 تفاصيل الشراء والتكلفة:")
                
                unit_type = st.selectbox("كيف تم شراء هذا الصنف؟", ["وحدة / كيلو (مفرد)", "صندوق / كرتونة (تحتوي على قطع)"])
                
                col_i3, col_i4, col_i5 = st.columns(3)
                if unit_type == "صندوق / كرتونة (تحتوي على قطع)":
                    box_count = col_i3.number_input("عدد الصناديق/الكراتين المشتراة:", min_value=0.0, value=1.0, step=1.0)
                    items_per_box = col_i4.number_input("عدد القطع داخل الصندوق الواحد:", min_value=1.0, value=12.0, step=1.0)
                    box_buy_price = col_i5.number_input("سعر شراء الصندوق الإجمالي (د.ل):", min_value=0.0, value=0.0, step=1.0)
                    
                    # الحسابات التلقائية
                    i_qty = box_count * items_per_box  # إجمالي عدد القطع
                    i_buy = box_buy_price / items_per_box if items_per_box > 0 else 0.0  # تكلفة القطعة الواحدة
                else:
                    i_qty = col_i3.number_input("الكمية (بالقطعة أو الكيلو):", min_value=0.0, value=1.0, step=1.0)
                    i_buy = col_i4.number_input("سعر شراء الوحدة/الكيلو (د.ل):", min_value=0.0, value=0.0, step=0.5)
                    col_i5.text_input("ملاحظة:", value="شراء مفرد", disabled=True)

                st.markdown("---")
                st.markdown("#### 💰 تفاصيل البيع للزبون (قطاعي):")
                col_s1, col_s2 = st.columns(2)
                i_sale = col_s1.number_input("سعر بيع القطعة / الكيلو الواحد (د.ل):", min_value=0.0, value=0.0, step=0.5)
                i_fav = col_s2.selectbox("إضافة للمفضلة في شاشة البيع؟", ["لا", "نعم"])
                
                uploaded_img = st.file_uploader("صورة الصنف (اختياري - JPG/PNG):", type=["jpg", "png", "jpeg"])
                
                if st.form_submit_button("💾 حفظ الصنف", type="primary"):
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
                            st.success(f"✅ تمت الإضافة! (تم إدخال {i_qty} قطعة/كيلو للمخزن، تكلفة الوحدة: {i_buy:.2f} د.ل)")
                            st.rerun()
                        except Exception as e:
                            st.error(f"⚠️ حدث خطأ (ربما كود الصنف موجود مسبقاً): {e}")
                    else:
                        st.warning("⚠️ يرجى إدخال كود الصنف واسمه.")
