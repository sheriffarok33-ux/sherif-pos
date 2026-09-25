import streamlit as st
import pandas as pd
import os
from database import get_db_connection

def show_page():
    st.markdown("""
        <style>
        .rtl-container { direction: rtl !important; text-align: right !important; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<h2 class="rtl-container">📦 إدارة المخزن وإضافة الأصناف (النظام المستقر للباركود)</h2>', unsafe_allow_html=True)
    st.markdown("---")
    
    conn = get_db_connection()
    
    # جلب الفروع أولاً
    branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    b_dict = {b["branch_name"]: b["id"] for b in branches}
    
    if not b_dict:
        st.warning("⚠️ يرجى إضافة فرع أو مخزن أولاً من تبويب إدارة الفروع.")
        conn.close()
        return

    selected_branch_name = st.selectbox("اختر الفرع / المخزن لتسجيل الأصناف:", list(b_dict.keys()))
    target_branch_id = b_dict[selected_branch_name]

    st.markdown("### 🏷️ إضافة صنف جديد بالباركود والكراتين (نموذج مستقر)")
    st.info("💡 نصيحة: بعد تمرير قارئ الباركود في خانة الكود، ستثبت الكتابة ولن تختفي أبداً حتى تضغط زر الحفظ.")

    # استخدام نموذج (Form) واحد متكامل يمنع إعادة التحميل العشوائي ويحافظ على المدخلات
    with st.form("stable_item_form", clear_on_submit=True):
        col_b1, col_b2 = st.columns(2)
        i_code = col_b1.text_input("كود الصنف (الباركود):")
        i_name = col_b2.text_input("اسم الصنف:")
        
        col_c1, col_c2 = st.columns(2)
        pieces_per_carton = col_c1.number_input("كم قطعة داخل الكرتون؟", min_value=1, value=1, step=1)
        cartons_count = col_c2.number_input("عدد الكراتين المضافة (الكمية):", min_value=0.0, value=1.0, step=1.0)
        
        col_p1, col_p2 = st.columns(2)
        box_buy_price = col_p1.number_input("سعر شراء الكرتون (د.ل):", min_value=0.0, value=0.0, step=0.5)
        sale_price_piece = col_p2.number_input("سعر بيع القطعة المفردة (د.ل):", min_value=0.0, value=0.0, step=0.5)
        
        i_fav = st.selectbox("إضافة لوحة المفضلة السريعة؟", ["لا", "نعم"])
        
        submit_clicked = st.form_submit_button("💾 حفظ وإضافة الصنف للمخزن", type="primary")
        
        if submit_clicked:
            if i_code.strip() and i_name.strip():
                # حساب إجمالي القطع وتكلفة القطعة الواحدة تلقائياً
                total_pieces = cartons_count * pieces_per_carton
                unit_buy_price = (box_buy_price / pieces_per_carton) if pieces_per_carton > 0 else 0.0
                fav_val = 1 if i_fav == "نعم" else 0
                
                try:
                    cursor = conn.cursor()
                    # التحقق هل الصنف موجود مسبقاً بنفس الفرع
                    existing = cursor.execute(
                        "SELECT id FROM items WHERE item_code = ? AND branch_id = ?", 
                        (i_code.strip(), target_branch_id)
                    ).fetchone()
                    
                    if existing:
                        st.error(f"⚠️ كود الصنف ({i_code}) موجود مسبقاً في هذا الفرع!")
                    else:
                        cursor.execute("""
                            INSERT INTO items (item_code, item_name, branch_id, quantity, buy_price, sale_price, avg_cost, favorite_rank)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            i_code.strip(), 
                            i_name.strip(), 
                            target_branch_id, 
                            total_pieces, 
                            unit_buy_price, 
                            sale_price_piece, 
                            unit_buy_price, 
                            fav_val
                        ))
                        conn.commit()
                        st.success(f"✅ تمت إضافة الصنف ({i_name.strip()}) بنجاح بإجمالي قطع: {total_pieces}!")
                except Exception as e:
                    st.error(f"⚠️ حدث خطأ أثناء الحفظ: {e}")
            else:
                st.warning("⚠️ يرجى إدخال كود الصنف واسمه على الأقل.")

    st.markdown("---")
    st.markdown("### 📋 الأصناف المسجلة في هذا الفرع")
    items_df = pd.read_sql("""
        SELECT item_code AS 'الكود', 
               item_name AS 'اسم الصنف', 
               quantity AS 'الكمية (قطع)', 
               buy_price AS 'تكلفة القطعة', 
               sale_price AS 'سعر البيع' 
        FROM items 
        WHERE branch_id = ?
    """, conn, params=(target_branch_id,))
    
    if not items_df.empty:
        st.dataframe(items_df, use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد أصناف مسجلة في هذا الفرع حتى الآن.")

    conn.close()
