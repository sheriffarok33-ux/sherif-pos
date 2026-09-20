import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("📦 إدارة المخزن والفروع والأصناف")
    st.info("💡 لوحة التحكم المركزية للأصناف: عرض الأرصدة، متوسط التكلفة، هامش الربح، التعديل المباشر، الدعم الكامل لقارئ الباركود، والاستيراد.")

    conn = get_db_connection()
    
    # جلب الفروع
    branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ يرجى إضافة فروع أو مخازن أولاً.")
        conn.close()
        return

    branch_dict = {b["branch_name"]: b["id"] for b in branches}
    
    # اختيار الفرع للعرض والإدارة
    sel_branch_name = st.selectbox("اختر الفرع أو المخزن للإدارة:", list(branch_dict.keys()))
    current_b_id = branch_dict[sel_branch_name]

    st.markdown("---")

    # تقسيم الشاشة إلى تبويبات احترافية
    tab1, tab2, tab3 = st.tabs([
        "📋 عرض الأصناف وأرصدتها وهامش الربح", 
        "➕ إدخال صنف جديد (مع قارئ الباركود)", 
        "📁 استيراد وتحديث عبر Excel"
    ])

    # --- التبويب الأول: عرض وتعديل الأصناف وأرصدتها وهامش الربح ---
    with tab1:
        st.subheader(f"📋 جدول أصناف وأرصدة: ({sel_branch_name})")
        st.markdown("💡 *يمكنك التعديل المباشر على أي خلية في الجدول أدناه (الكمية، الأسعار، الكود، الاسم) ثم الضغط على زر الحفظ والتحديث.*")

        # جلب الأصناف مع حساب هامش الربح ومتوسط التكلفة
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
            # حساب هامش الربح ديناميكياً للعرض
            items_df['هامش الربح (د.ل)'] = items_df['سعر البيع'] - items_df['متوسط التكلفة']
            items_df['نسبة الربح %'] = ((items_df['هامش الربح (د.ل)'] / items_df['متوسط التكلفة']) * 100).fillna(0).round(1)

            # استخدام Data Editor للتعديل المباشر
            edited_df = st.data_editor(
                items_df, 
                hide_index=True, 
                use_container_width=True,
                key=f"inventory_editor_{current_b_id}"
            )

            col_save1, col_save2 = st.columns([1, 3])
            with col_save1:
                if st.button("💾 حفظ التعديلات", type="primary", use_container_width=True):
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
            with col_save2:
                # زر لتصدير الجدول الحالي إكسيل
                csv_data = edited_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 تصدير الجدول الحالي (CSV)",
                    data=csv_data,
                    file_name=f"Inventory_{sel_branch_name}.csv",
                    mime="text/csv"
                )
        else:
            st.info("لا توجد أصناف مسجلة في هذا الفرع حالياً.")

    # --- التبويب الثاني: إدخال صنف جديد مع قارئ الباركود ---
    with tab2:
        st.subheader("➕ إدخال صنف جديد (يدعم ماسح الباركود الفعلي)")
        st.markdown("📌 **خطوات الاستخدام:** قم بالنقر داخل خانة (كود الصنف/الباركود) واستخدم قارئ الباركود (Barcode Scanner) لقراءة الكود، ثم استكمل باقي الحقول يدوياً.")

        with st.form("manual_barcode_item_form", clear_on_submit=True):
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                # حقل مخصص لقرائة الكود بالماسح الضوئي
                m_code = st.text_input("كود الصنف / الباركود (امسح بالكاميرا أو القارئ):", placeholder="اضغط هنا ثم امسح الكود...")
                m_name = st.text_input("اسم الصنف *:")
                m_qty = st.number_input("الكمية الابتدائية:", min_value=0.0, value=0.0, step=0.5)
            with col_b2:
                m_buy = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=0.0, step=0.5)
                m_sale = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=0.0, step=0.5)
                m_expiry = st.text_input("تاريخ الصلاحية (اختياري):", value="")

            # خيار لتعميم الصنف الجديد على كافة الفروع أو الفرع الحالي فقط
            apply_scope = st.radio("نطاق إضافة هذا الصنف:", ["📍 للفرع الحالي فقط", "🌐 تعميم لكافة الفروع والمخازن"], horizontal=True)

            if m_sale > 0 and m_buy > 0:
                calc_margin = m_sale - m_buy
                calc_percent = (calc_margin / m_buy) * 100
                st.info(f"📊 معاينة سريعة: هامش الربح المتوقع = **{calc_margin:.2f} د.ل** ({calc_percent:.1f}%)")

            submitted_barcode_form = st.form_submit_button("💾 حفظ وإضافة الصنف", type="primary", use_container_width=True)

            if submitted_barcode_form:
                if not m_name.strip():
                    st.warning("⚠️ اسم الصنف حقل إلزامي!")
                else:
                    cur_m = conn.cursor()
                    target_b_ids = [b["id"] for b in branches] if "كافة الفروع" in apply_scope else [current_b_id]
                    
                    try:
                        for b_id in target_b_ids:
                            # التحقق مما إذا كان الصنف موجوداً مسبقاً بنفس الكود في هذا الفرع
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
                        st.success(f"✅ تم حفظ الصنف ({m_name}) بنجاح!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"⚠️ خطأ أثناء الحفظ: {e}")

    # --- التبويب الثالث: الاستيراد عبر Excel ---
    with tab3:
        st.subheader("📁 استيراد وتحديث الأصناف عبر ملف Excel / CSV")
        st.markdown("""
        **تنبيهات الملف:** يجب أن يحتوي الملف على الأعمدة التالية تماماً:
        `كود الصنف` | `اسم الصنف` | `سعر البيع` | `سعر الشراء` | `الكمية` | `تاريخ الصلاحية`
        """)

        import_scope = st.radio("نطاق الاستيراد:", ["📍 للفرع المختار حالياً", "🌐 تعميم لكافة الفروع"], horizontal=True, key="imp_scope_radio")
        uploaded_excel = st.file_uploader("اختر ملف الإكسيل (.xlsx أو .csv)", type=["xlsx", "csv"])

        if uploaded_excel is not None:
            try:
                if uploaded_excel.name.endswith('.csv'):
                    df_imp = pd.read_csv(uploaded_excel)
                else:
                    df_imp = pd.read_excel(uploaded_excel)

                st.markdown("### 🔍 معاينة البيانات المرفوعة:")
                st.dataframe(df_imp.head(), use_container_width=True)

                if st.button("🚀 تنفيذ استيراد وترحيل البيانات", type="primary"):
                    cur_imp = conn.cursor()
                    count_imported = 0
                    target_b_list = [b["id"] for b in branches] if "كافة الفروع" in import_scope else [current_b_id]

                    for _, row in df_imp.iterrows():
                        if row.isna().all(): continue
                        code_val = str(row.get("كود الصنف", "")).strip()
                        name_val = str(row.get("اسم الصنف", "")).strip()
                        if name_val.lower() in ["nan", "none", ""]: continue

                        qty_val = float(row.get("الكمية", 0.0))
                        buy_val = float(row.get("سعر الشراء", 0.0))
                        sale_val = float(row.get("سعر البيع", 0.0))
                        exp_val = str(row.get("تاريخ الصلاحية", "")).strip()

                        for b_id in target_b_list:
                            chk_item = cur_imp.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (b_id, code_val)).fetchone()
                            if chk_item:
                                cur_imp.execute("""
                                    UPDATE items SET item_name = ?, quantity = ?, buy_price = ?, sale_price = ?, avg_cost = ?, expiry_date = ?
                                    WHERE id = ?
                                """, (name_val, qty_val, buy_val, sale_val, buy_val, exp_val, chk_item["id"]))
                            else:
                                cur_imp.execute("""
                                    INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, expiry_date, no_expiry, favorite_rank)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                                """, (b_id, code_val, name_val, qty_val, buy_val, sale_val, buy_val, exp_val))
                        count_imported += 1

                    conn.commit()
                    st.success(f"✅ تم استيراد ومعالجة ({count_imported}) صنفاَ بنجاح تام!")
                    st.rerun()
            except Exception as e:
                st.error(f"خطأ أثناء قراءة الملف: {e}")

    conn.close()
