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

    st.markdown('<h2 class="rtl-container">📦 إدارة المخزن - نظام الكراتين والقطع والباركود المتقدم</h2>', unsafe_allow_html=True)
    st.markdown("---")
    
    conn = get_db_connection()
    
    # جلب الفروع والمخازن
    branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    b_dict = {b["branch_name"]: b["id"] for b in branches}
    
    if not b_dict:
        st.warning("⚠️ يرجى إنشاء مخزن أو فرع أولاً من إدارة الفروع.")
        conn.close()
        return

    selected_branch = st.selectbox("اختر المخزن أو الفرع الحالي:", list(b_dict.keys()))
    target_branch_id = b_dict[selected_branch]

    st.markdown("### 🏷️ إضافة أو تحديث صنف (نظام الكراتين والقطع والباركود)")
    
    # نموذج مدخلات دقيق يدعم الكراتين والقطع والباركود بدون مسح
    with st.form("inventory_master_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        item_code = col1.text_input("كود الصنف (الباركود - مرر القارئ هنا):")
        item_name = col2.text_input("اسم الصنف:")
        
        col3, col4 = st.columns(2)
        pieces_per_carton = col3.number_input("كم قطعة داخل الكرتون الواحد؟", min_value=1, value=1, step=1)
        cartons_count = col4.number_input("عدد الكراتين المضافة (الكمية):", min_value=0.0, value=1.0, step=1.0)
        
        col5, col6 = st.columns(2)
        box_buy_price = col5.number_input("سعر شراء الكرتون بالكامل (د.ل):", min_value=0.0, value=0.0, step=0.5)
        sale_price_piece = col6.number_input("سعر بيع القطعة المفردة (د.ل):", min_value=0.0, value=0.0, step=0.5)
        
        # حسابات توضيحية تظهر للمستخدم قبل الحفظ
        total_pieces = cartons_count * pieces_per_carton
        unit_buy_price = (box_buy_price / pieces_per_carton) if pieces_per_carton > 0 else 0.0
        
        st.info(f"📊 ملخص الحسبة التلقائية: إجمالي القطع = **{total_pieces} قطعة** | تكلفة القطعة الواحدة = **{unit_buy_price:,.2f} د.ل**")
        
        fav_choice = st.selectbox("إضافة إلى لوحة المفضلة السريعة؟", ["لا", "نعم"])
        
        submitted = st.form_submit_button("💾 حفظ الصنف في المخزن", type="primary")
        
        if submitted:
            if item_code.strip() and item_name.strip():
                fav_val = 1 if fav_choice == "نعم" else 0
                cursor = conn.cursor()
                
                # التحقق هل الصنف موجود مسبقاً بنفس الفرع
                existing = cursor.execute(
                    "SELECT id, quantity FROM items WHERE item_code = ? AND branch_id = ?", 
                    (item_code.strip(), target_branch_id)
                ).fetchone()
                
                if existing:
                    # تحديث الكمية والسعر لو الصنف موجود مسبقاً
                    cursor.execute(
                        "UPDATE items SET quantity = quantity + ?, buy_price = ?, sale_price = ?, avg_cost = ? WHERE id = ?",
                        (total_pieces, unit_buy_price, sale_price_piece, unit_buy_price, existing['id'])
                    )
                    conn.commit()
                    st.success(f"✅ الصنف مسجل مسبقاً، وتم تحديث الكمية بإضافة ({total_pieces} قطعة) وتحديث الأسعار بنجاح!")
                else:
                    # إضافة صنف جديد كلياً
                    cursor.execute("""
                        INSERT INTO items (item_code, item_name, branch_id, quantity, buy_price, sale_price, avg_cost, favorite_rank)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        item_code.strip(), 
                        item_name.strip(), 
                        target_branch_id, 
                        total_pieces, 
                        unit_buy_price, 
                        sale_price_piece, 
                        unit_buy_price, 
                        fav_val
                    ))
                    conn.commit()
                    st.success(f"✅ تمت إضافة الصنف الجديد ({item_name.strip()}) بنجاح بإجمالي {total_pieces} قطعة!")
            else:
                st.warning("⚠️ يرجى التأكد من إدخال كود الصنف (الباركود) واسم الصنف.")

    st.markdown("---")
    st.markdown("### 📋 جدول الأصناف المسجلة في هذا المخزن")
    items_df = pd.read_sql("""
        SELECT item_code AS 'الكود', 
               item_name AS 'اسم الصنف', 
               quantity AS 'الكمية الإجمالية (قطع)', 
               buy_price AS 'تكلفة القطعة', 
               sale_price AS 'سعر بيع القطعة' 
        FROM items 
        WHERE branch_id = ?
    """, conn, params=(target_branch_id,))
    
    if not items_df.empty:
        st.dataframe(items_df, use_container_width=True, hide_index=True)
    else:
        st.info("لا توجد أصناف مسجلة في هذا المخزن حتى الآن.")

    conn.close()
