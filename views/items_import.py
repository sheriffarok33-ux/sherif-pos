import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("📁 إدارة الأصناف: الاستيراد والإدخال اليدوي")
    st.info("💡 قم برفع ملف Excel الخاص بالأصناف أو إضافتها يدوياً مع خيار تعميمها على كافة الفروع أو فرع محدد.")

    conn = get_db_connection()
    
    # جلب الفروع لتغذية القائمة المنسدلة الدائمة
    branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ يرجى إضافة فروع أولاً من شاشة إدارة الفروع.")
        conn.close()
        return

    branch_dict = {b["branch_name"]: b["id"] for b in branches}

    # خيار اختيار نطاق الترحيل (لكافة الفروع أو فرع محدد عبر الدروب ليست)
    st.markdown("### 🎯 نطاق تطبيق الأصناف (الترحيل)")
    target_mode = st.radio(
        "اختر طريقة توزيع الأصناف:", 
        ["🌐 ترحيل لكافة الفروع والمخازن تلقائياً", "📍 فرع أو مخزن محدد (من القائمة المنسدلة)"],
        horizontal=True
    )
    
    selected_branch_id = None
    if "فرع محدد" in target_mode:
        sel_b_name = st.selectbox("اختر الفرع المستهدف من القائمة:", list(branch_dict.keys()))
        selected_branch_id = branch_dict[sel_b_name]

    st.markdown("---")

    # تقسيم الشاشة إلى تبويبات (استيراد ملف vs إدخال يدوي)
    tab1, tab2 = st.tabs(["📊 استيراد ملف أصناف (Excel / CSV)", "✍️ إدخال صنف جديد يدوياً"])

    # --- التبويب الأول: استيراد ملف Excel ---
    with tab1:
        st.subheader("📁 رفع ملف الأصناف")
        st.markdown("""
        **تنبيه:** يجب أن يحتوي الملف على الأعمدة التالية تماماً كما في جدولك:
        `كود الصنف` | `اسم الصنف` | `سعر البيع` | `سعر الشراء` | `الكمية` | `تاريخ الصلاحية`
        """)

        uploaded_file = st.file_uploader("اختر ملف Excel أو CSV", type=["xlsx", "csv"])
        
        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)

                st.markdown("### 🔍 معاينة البيانات المستوردة:")
                st.dataframe(df.head(), use_container_width=True)

                if st.button("🚀 اعتماد وترحيل الأصناف من الملف", type="primary"):
                    conn_imp = get_db_connection()
                    success_count = 0
                    
                    # تحديد الفروع المستهدفة بناءً على اختيار المستخدم
                    target_branches = [b["id"] for b in branches] if "كافة الفروع" in target_mode else [selected_branch_id]

                    for _, row in df.iterrows():
                        code = str(row.get("كود الصنف", "")).strip()
                        name = str(row.get("اسم الصنف", "")).strip()
                        sale_p = float(row.get("سعر البيع", 0.0))
                        buy_p = float(row.get("سعر الشراء", 0.0))
                        qty = float(row.get("الكمية", 0.0))
                        expiry = str(row.get("تاريخ الصلاحية", "")).strip()

                        if name and name != "nan":
                            for b_id in target_branches:
                                # التحقق إذا كان الصنف موجوداً مسبقاً في هذا الفرع لتحديثه أو إضافته
                                existing = conn_imp.execute(
                                    "SELECT id FROM items WHERE branch_id = ? AND (item_code = ? OR item_name = ?)", 
                                    (b_id, code, name)
                                ).fetchone()

                                if existing:
                                    conn_imp.execute("""
                                        UPDATE items SET quantity = quantity + ?, sale_price = ?, buy_price = ?, expiry_date = ?
                                        WHERE id = ?
                                    """, (qty, sale_p, buy_p, expiry, existing["id"]))
                                else:
                                    conn_imp.execute("""
                                        INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, expiry_date)
                                        VALUES (?, ?, ?, ?, ?, ?, ?)
                                    """, (b_id, code, name, qty, buy_p, sale_p, expiry))
                            success_count += 1

                    conn_imp.commit()
                    conn_imp.close()
                    st.success(f"✅ تمت معالجة وترحيل {success_count} صنفاَ بنجاح تام!")
            except Exception as e:
                st.error(f قراءة الملف: {e}")

    # --- التبويب الثاني: إدخال صنف جديد يدوياً ---
    with tab2:
        st.subheader("✍️ إضافة صنف جديد للنظام")
        with st.form("manual_item_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                m_code = st.text_input("كود الصنف (الباركود):")
                m_name = st.text_input("اسم الصنف *:")
                m_buy = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=0.0, step=0.5)
            with col2:
                m_sale = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=0.0, step=0.5)
                m_qty = st.number_input("الكمية الابتدائية:", min_value=0.0, value=0.0, step=0.5)
                m_expiry = st.text_input("تاريخ الصلاحية (اختياري - مثلاً 2027/12):", value="")

            # حساب هامش الربح التجريبي للمعاينة أمام المستخدم
            if m_sale > 0 and m_buy > 0:
                profit_margin = m_sale - m_buy
                profit_percent = (profit_margin / m_buy) * 100
                st.info(f"📊 معاينة حسابية: هامش الربح للقطعة = **{profit_margin:.2f} د.ل** ({profit_percent:.1f}%)")

            submitted_manual = st.form_submit_button("💾 حفظ وإضافة الصنف", type="primary", use_container_width=True)

            if submitted_manual:
                if not m_name.strip():
                    st.warning("⚠️ اسم الصنف حقل إلزامي!")
                else:
                    conn_m = get_db_connection()
                    target_branches = [b["id"] for b in branches] if "كافة الفروع" in target_mode else [selected_branch_id]
                    
                    try:
                        for b_id in target_branches:
                            conn_m.execute("""
                                INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, expiry_date)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (b_id, m_code.strip(), m_name.strip(), m_qty, m_buy, m_sale, m_expiry))
                        
                        conn_m.commit()
                        conn_m.close()
                        st.success(f"✅ تم إضافة الصنف ({m_name}) بنجاح وتعميمه بحسب الخيار المحدد!")
                        st.rerun()
                    except Exception as e:
                        conn_m.close()
                        st.error(f"⚠️ خطأ أثناء الحفظ: {e}")

    conn.close()
