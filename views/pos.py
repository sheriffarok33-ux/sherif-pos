with pos_tab1:
        fav_items = conn.execute("SELECT * FROM items WHERE favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC" if b_id=="ALL" else "SELECT * FROM items WHERE branch_id = ? AND favorite_rank BETWEEN 1 AND 20 ORDER BY favorite_rank ASC", (() if b_id=="ALL" else (b_id,))).fetchall()
        
        st.text_input("🔍 مسح باركود الميزان أو الباركود العادي الفوري:", key="barcode_scan", on_change=process_scale_barcode)

        col_g, col_c = st.columns([2, 1])
        
        with col_g:
            st.subheader("⭐ الأصناف المفضلة للكاشير (اضغط مباشرة للإضافة)")
            
            # حقل لتحديد كمية البيع السريع افتراضياً (مثلاً 1 كجم، ويمكن للكاشير تعديلها أو استخدام أزرار الكميات)
            quick_qty = st.number_input("الكمية الافتراضية للبيع السريع (كجم):", min_value=0.1, value=1.0, step=0.5, format="%.2f")

            if fav_items:
                # تقسيم الأصناف المفضلة على أعمدة لتبدو مثل الأزرار البارزة (Push Buttons)
                for item in fav_items:
                    qty_val = float(item['quantity'])
                    color_q = "green" if qty_val > 0 else "red"
                    
                    c_info, c_btn = st.columns([3, 1])
                    with c_info:
                        st.markdown(f"🔹 <b>{item['item_name']}</b> | السعر: <code>{item['sale_price']} د.ل</code> | <span style='color:{color_q}; font-size:12px;'>المتاح: {qty_val} كجم</span>", unsafe_allow_html=True)
                    with c_btn:
                        # زر Push Button مباشر وفوري للإضافة بالسلة
                        if st.button("➕ إضافة", key=f"fast_add_{item['id']}", use_container_width=True):
                            if qty_val <= 0:
                                st.toast(f"⚠️ تنبيه: الصنف ({item['item_name']}) منتهي في النظام! يرجى إبلاغ المدير لإضافة فائض.", icon="🚨")
                            
                            st.session_state["cart"].append({
                                "id": item["id"], 
                                "name": item["item_name"], 
                                "price": float(item["sale_price"]), 
                                "qty": float(quick_qty), 
                                "total": float(item["sale_price"]) * float(quick_qty)
                            })
                            st.rerun()
                    st.markdown("---")
            else:
                st.info("لا توجد أصناف مفضلة محددة (1 إلى 20). يمكنك ترتيبها من شاشة المفضلة.")
                
        # سلة المبيعات
        with col_c:
            st.subheader("🛒 سلة المبيعات الحالية")
            if st.session_state.get("cart"):
                for index, cart_item in enumerate(st.session_state["cart"]):
                    col_item_desc, col_item_del = st.columns([3, 1])
                    with col_item_desc:
                        st.markdown(f"**{cart_item['name']}**<br>`{cart_item['qty']} كجم` × `{cart_item['price']}` = **{cart_item['total']:,.2f} د.ل**", unsafe_allow_html=True)
                    with col_item_del:
                        if st.button("❌", key=f"del_cart_item_{index}", help="حذف الصنف"):
                            st.session_state["cart"].pop(index)
                            st.rerun()
                    st.markdown("---")
                    
                g_tot = sum([x["total"] for x in st.session_state["cart"]])
                st.metric("الإجمالي النهائي", f"{g_tot:,.2f} د.ل")
                if st.button("🖨️ إتمام وطباعة الفاتورة", type="primary", use_container_width=True): 
                    checkout_payment_dialog(b_id, g_tot)
                if st.button("🗑️ تفريغ السلة بالكامل", use_container_width=True): 
                    st.session_state["cart"] = []
                    st.rerun()
            else:
                st.info("السلة فارغة حالياً.")
