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

    st.markdown('<h2 class="rtl-container">📦 إدارة المخزن وإضافة الأصناف بالباركود والكراتين</h2>', unsafe_allow_html=True)
    st.markdown("---")
    
    conn = get_db_connection()
    
    # 1. تهيئة الذاكرة لحفظ الباركود وثباته
    if "active_barcode" not in st.session_state:
        st.session_state["active_barcode"] = ""

    # دالة لتثبيت الكود المقروء
    def handle_scan():
        scanned = st.session_state.get("scanner_input", "")
        if scanned:
            st.session_state["active_barcode"] = scanned.strip()

    # حقل مسح الباركود (يستقبل الإدخال من القارئ ويثبته فوراً)
    st.text_input(
        "🏷️ قم بمسح الباركود بالقارئ (أو اكتبه واضغط Enter):", 
        key="scanner_input", 
        on_change=handle_scan
    )

    # إذا كان هناك باركود نشط وثابت في الذاكرة
    current_code = st.session_state["active_barcode"]

    if current_code:
        st.success(f"🎯 الكود الحالي الثابت: **{current_code}**")
        
        # زر لإلغاء وتغيير الكود لو أردت مسح صنف آخر
        if st.button("🔄 مسح صنف آخر (إعادة تعيين الكود)"):
            st.session_state["active_barcode"] = ""
            st.session_state["scanner_input"] = ""
            st.rerun()

        # جلب الفروع
        branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
        b_dict = {b["branch_name"]: b["id"] for b in branches}
        
        if not b_dict:
            st.warning("⚠️ يرجى إضافة فرع أو مخزن أولاً.")
        else:
            selected_branch_name = st.selectbox("اختر الفرع / المخزن لتسجيل الصنف:", list(b_dict.keys()), key="branch_sel_box")
            target_branch_id = b_dict[selected_branch_name]
            
            # التحقق هل الصنف مسجل مسبقاً بهذا الفرع؟
            existing_item = conn.execute(
                "SELECT * FROM items WHERE item_code = ? AND branch_id = ?", 
                (current_code, target_branch_id)
            ).fetchone()
            
            if existing_item:
                st.info(f"ℹ️ الصنف مسجل مسبقاً باسم: **{existing_item['item_name']}** (الكمية الحالية: {existing_item['quantity']})")
                with st.form("update_qty_form"):
                    add_qty = st.number_input("إضافة كمية جديدة للمخزون:", min_value=0.0, value=1.0, step=1.0)
                    if st.form_submit_button("➕ تحديث المخزون", type="primary"):
                        conn.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (add_qty, existing_item['id']))
                        conn.commit()
                        st.success("✅ تم تحديث كمية المخزون بنجاح!")
                        st.session_state["active_barcode"] = ""
                        st.session_state["scanner_input"] = ""
                        st.rerun()
            else:
                # نموذج إدخال تفاصيل الصنف الجديد بالكراتين والقطع (خارج نماذج الباركود المتطايرة لضمان الثبات التام)
                with st.form("new_item_carton_form"):
                    st.markdown("### 📝 تسجيل صنف جديد (دعم نظام الكراتين والقطع)")
                    
                    i_name = st.text_input("اسم الصنف:")
                    
                    col1, col2 = st.columns(2)
                    pieces_per_carton = col1.number_input("كم قطعه داخل الكرتون؟", min_value=1, value=1, step=1)
                    cartons_count = col2.number_input("عدد الكراتين المضافة (الكمية):", min_value=0.0, value=1.0, step=1.0)
                    
                    total_pieces = cartons_count * pieces_per_carton
                    st.info(f"📦 إجمالي عدد القطع المضافة للمخزون تلقائياً: **{total_pieces} قطعة**")
                    
                    col3, col4 = st.columns(2)
                    box_buy_price = col3.number_input("سعر شراء الكرتون (د.ل):", min_value=0.0, value=0.0, step=0.5)
                    sale_price_piece = col4.number_input("سعر بيع القطعة المفردة (د.ل):", min_value=0.0, value=0.0, step=0.5)
                    
                    unit_buy_price = (box_buy_price / pieces_per_carton) if pieces_per_carton > 0 else 0.0
                    st.caption(f"💡 سعر تكلفة القطعة الواحدة محسوب تلقائياً: {unit_buy_price:,.2f} د.ل")
                    
                    i_fav = st.selectbox("إضافة لوحة المفضلة السريعة؟", ["لا", "نعم"])
                    
                    submit_btn = st.form_submit_button("💾 حفظ الصنف وإضافته للمخزن", type="primary")
                    if submit_btn:
                        if i_name.strip():
                            fav_val = 1 if i_fav == "نعم" else 0
                            cursor = conn.cursor()
                            cursor.execute("""
                                INSERT INTO items (item_code, item_name, branch_id, quantity, buy_price, sale_price, avg_cost, favorite_rank)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                current_code, 
                                i_name.strip(), 
                                target_branch_id, 
                                total_pieces, 
                                unit_buy_price, 
                                sale_price_piece, 
                                unit_buy_price, 
                                fav_val
                            ))
                            conn.commit()
                            st.success(f"✅ تمت إضافة الصنف ({i_name}) بنجاح للمخزن!")
                            st.session_state["active_barcode"] = ""
                            st.session_state["scanner_input"] = ""
                            st.rerun()
                        else:
                            st.warning("⚠️ يرجى إدخال اسم الصنف على الأقل.")
    else:
        st.info("💡 يرجى تمرير قارئ الباركود على المنتج أو كتابة الكود والضغط على Enter ليبدأ النظام في تسجيل الصنف.")

    conn.close()
