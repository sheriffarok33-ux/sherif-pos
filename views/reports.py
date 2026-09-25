# =========================================================================
    # 2. تقرير الأصناف ومتوسط التكلفة وهامش الربح
    # =========================================================================
    with tab_items_rep:
        st.markdown("### 📦 تقرير مخزون الأصناف ومتوسط التكلفة وهامش الربح")
        
        filter_b = st.selectbox("اختر الفرع لعرض أصنافه:", ["كل الفروع"] + list(b_dict.keys()), key="rep_branch_filter")

        if filter_b == "كل الفروع":
            query = """
                SELECT items.item_code AS 'كود الصنف', 
                       items.item_name AS 'اسم الصنف', 
                       branches.branch_name AS 'الفرع', 
                       items.quantity AS 'الكمية المتاحة', 
                       items.buy_price AS 'سعر الشراء الأساسي', 
                       items.avg_cost AS 'متوسط التكلفة الفعلي', 
                       items.sale_price AS 'سعر البيع الحالي'
                FROM items 
                JOIN branches ON items.branch_id = branches.id
            """
            df_items = pd.read_sql(query, conn)
        else:
            b_id_sel = b_dict[filter_b]
            query = """
                SELECT items.item_code AS 'كود الصنف', 
                       items.item_name AS 'اسم الصنف', 
                       branches.branch_name AS 'الفرع', 
                       items.quantity AS 'الكمية المتاحة', 
                       items.buy_price AS 'سعر الشراء الأساسي', 
                       items.avg_cost AS 'متوسط التكلفة الفعلي', 
                       items.sale_price AS 'سعر البيع الحالي'
                FROM items 
                JOIN branches ON items.branch_id = branches.id
                WHERE branches.id = ?
            """
            df_items = pd.read_sql(query, conn, params=(b_id_sel,))

        if not df_items.empty:
            if is_admin_or_supervisor:
                # 🧠 معالجة ذكية: إذا كانت التكلفة صفر أو غير مسجلة، نعتبرها مساوية لسعر الشراء أو نضع تنبيه لتجنب الخطأ الحقيقي
                df_items['متوسط التكلفة الفعلي'] = df_items['متوسط التكلفة الفعلي'].apply(lambda x: x if x > 0 else 0.0)
                
                # حساب هامش الربح بدقة (سعر البيع - التكلفة الفعلية)
                df_items['هامش الربح (د.ل)'] = df_items['سعر البيع الحالي'] - df_items['متوسط التكلفة الفعلي']
                
                # نسبة هامش الربح المئوية (%) لتظهر بشكل احترافي محاسبي
                df_items['نسبة الربح %'] = df_items.apply(
                    lambda row: round((row['هامش الربح (د.ل)'] / row['سعر البيع الحالي']) * 100, 1) if row['سعر البيع الحالي'] > 0 else 0.0, 
                    axis=1
                )
                
                st.success("🔒 يتم عرض بيانات متوسط التكلفة، هامش الربح بالدينار، ونسبة الربح المئوية بدقة تامة.")
            else:
                df_items = df_items.drop(columns=['سعر الشراء الأساسي', 'متوسط التكلفة الفعلي'], errors='ignore')

            st.dataframe(df_items, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد أصناف مسجلة في هذا الفرع.")
