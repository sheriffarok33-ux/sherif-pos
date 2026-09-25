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

    st.markdown('<h2 class="rtl-container">📦 إدارة المخزن والفروع - النظام المطور للباركود والكراتين</h2>', unsafe_allow_html=True)
    st.markdown("---")
    
    conn = get_db_connection()
    
    tab_branches, tab_items, tab_transfer = st.tabs([
        "🏢 إدارة الفروع والمخازن", 
        "📋 تعريف وإدارة أصناف المخزن والباركود", 
        "🚚 تزويد ونقل البضائع بين الفروع"
    ])
    
    # ==========================================
    # 1. إدارة الفروع والمخازن
    # ==========================================
    with tab_branches:
        st.markdown("### ➕ إضافة فرع أو مخزن جديد")
        with st.form("add_branch_form", clear_on_submit=True):
            b_name = st.text_input("اسم الفرع أو المخزن الجديد:")
            b_type = st.selectbox("نوع المنشأة:", ["فرع بيع (كاشير)", "مخزن رئيسي"])
            
            if st.form_submit_button("💾 حفظ الفرع الجديد", type="primary"):
                if b_name.strip():
                    try:
                        conn.execute("INSERT INTO branches (branch_name, branch_type) VALUES (?, ?)", (b_name.strip(), b_type))
                        conn.commit()
                        st.success(f"✅ تم إضافة ({b_name}) بنجاح!")
                        st.rerun()
                    except:
                        st.error("⚠️ هذا الفرع موجود مسبقاً.")
                else:
                    st.warning("⚠️ يرجى إدخال اسم الفرع.")

        st.markdown("### 📊 الفروع والمخازن المسجلة حالياً")
        branches_df = pd.read_sql("SELECT id AS 'رقم الفرع', branch_name AS 'اسم الفرع', branch_type AS 'النوع' FROM branches", conn)
        if not branches_df.empty:
            st.dataframe(branches_df, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد فروع مسجلة حتى الآن.")

    # ==========================================
    # 2. تعريف وإدارة أصناف المخزن والباركود
    # ==========================================
    with tab_items:
        branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
        b_dict = {b["branch_name"]: b["id"] for b in branches}
        
        if not b_dict:
            st.warning("⚠️ يرجى إضافة فرع أو مخزن أولاً من تبويب 'إدارة الفروع'.")
        else:
            selected_branch_name = st.selectbox("اختر الفرع / المخزن للتعامل مع الأصناف:", list(b_dict.keys()), key="item_branch_sel")
            target_branch_id = b_dict[selected_branch_name]
            
            st.markdown("### 🏷️ تسجيل صنف جديد أو تحديثه (نظام الكراتين والقطع)")
            
            # نموذج متكامل وثابت لمنع مسح الباركود أو تطاير الحقول
            with st.form("stable_item_entry_form", clear_on_submit=True):
                col_f1, col_f2 = st.columns(2)
                i_code = col_f1.text_input("كود الصنف (الباركود):")
                i_name = col_f2.text_input("اسم الصنف:")
                
                col_f3, col_f4 = st.columns(2)
                pieces_per_carton = col_f3.number_input("كم قطعه داخل الكرتون؟", min_value=1, value=1, step=1)
                cartons_count = col_f4.number_input("عدد الكراتين المضافة (الكمية):", min_value=0.0, value=1.0, step=1.0)
                
                col_f5, col_f6 = st.columns(2)
                box_buy_price = col_f5.number_input("سعر شراء الكرتون (د.ل):", min_value=0.0, value=0.0, step=0.5)
                sale_price_piece = col_f6.number_input("سعر بيع القطعة المفردة (د.ل):", min_value=0.0, value=0.0, step=0.5)
                
                i_fav = st.selectbox("إضافة لوحة المفضلة السريعة؟", ["لا", "نعم"])
                uploaded_img = st.file_uploader("صورة الصنف (اختياري):", type=["jpg", "png", "jpeg"])
                
                submit_btn = st.form_submit_button("💾 حفظ الصنف وإضافته للمخزن", type="primary")
                
                if submit_btn:
                    if i_code.strip() and i_name.strip():
                        total_pieces = cartons_count * pieces_per_carton
                        unit_buy_price = (box_buy_price / pieces_per_carton) if pieces_per_carton > 0 else 0.0
                        fav_val = 1 if i_fav == "نعم" else 0
                        
                        try:
                            cursor = conn.cursor()
                            # التحقق هل الصنف موجود مسبقاً في هذا الفرع
                            existing = cursor.execute(
                                "SELECT id, quantity FROM items WHERE item_code = ? AND branch_id = ?", 
                                (i_code.strip(), target_branch_id)
                            ).fetchone()
                            
                            if existing:
                                # تحديث الكمية والسعر لو الصنف موجود
                                cursor.execute(
                                    "UPDATE items SET quantity = quantity + ?, sale_price = ?, buy_price = ? WHERE id = ?",
                                    (total_pieces, sale_price_piece, unit_buy_price, existing['id'])
                                )
                                conn.commit()
                                st.success(f"✅ الصنف موجود مسبقاً، وتم تحديث الكمية بإضافة {total_pieces} قطعة وسعر البيع بنجاح!")
                            else:
                                # إدراج صنف جديد كلياً
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
                                
                                if uploaded_img is not None:
                                    os.makedirs("item_images", exist_ok=True)
                                    img_path = os.path.join("item_images", f"{i_code.strip()}.jpg")
                                    with open(img_path, "wb") as f:
                                        f.write(uploaded_img.getbuffer())
                                        
                                conn.commit()
                                st.success(f"✅ تمت إضافة الصنف الجديد ({i_name.strip()}) بنجاح بإجمالي قطع: {total_pieces}!")
                        except Exception as e:
                            st.error(f"⚠️ حدث خطأ أثناء الحفظ: {e}")
                    else:
                        st.warning("⚠️ يرجى إدخال كود الصنف واسمه على الأقل.")

            st.markdown("---")
            st.markdown("### 📋 جدول الأصناف المسجلة في هذا المخزن")
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
                st.info("لا توجد أصناف مسجلة في هذا المخزن حتى الآن.")

    # ==========================================
    # 3. تزويد ونقل البضائع بين الفروع
    # ==========================================
    with tab_transfer:
        st.markdown("### 🚚 تزويد ونقل بضاعة من المخزن الرئيسي إلى فرع بيع")
        
        branches_list = conn.execute("SELECT id, branch_name FROM branches").fetchall()
        b_map = {b["branch_name"]: b["id"] for b in branches_list}
        
        if len(b_map) < 2:
            st.warning("⚠️ يجب أن يكون لديك فرعين أو مخزن على الأقل لتمكين عملية النقل والتزويد.")
        else:
            col_t1, col_t2 = st.columns(2)
            from_b = col_t1.selectbox("من مخزن (المصدر):", list(b_map.keys()), key="trans_from")
            to_b = col_t2.selectbox("إلى فرع (المستلم):", list(b_map.keys()), key="trans_to")
            
            if from_b == to_b:
                st.error("⚠️ لا يمكن النقل إلى نفس الفرع!")
            else:
                from_id = b_map[from_b]
                to_id = b_map[to_b]
                
                source_items = conn.execute("SELECT id, item_code, item_name, quantity, buy_price, sale_price FROM items WHERE branch_id = ?", (from_id,)).fetchall()
                s_items_dict = {f"[{i['item_code']}] {i['item_name']} (المتوفر: {i['quantity']})": i for i in source_items}
                
                if s_items_dict:
                    with st.form("transfer_item_form", clear_on_submit=True):
                        sel_trans_item_str = st.selectbox("اختر الصنف المراد نقله:", list(s_items_dict.keys()))
                        trans_qty = st.number_input("الكمية المراد نقلها وتزويدها:", min_value=0.01, value=1.0, step=1.0)
                        
                        if st.form_submit_button("🚀 تنفيذ عملية النقل والتزويد", type="primary"):
                            it_obj = s_items_dict[sel_trans_item_str]
                            if trans_qty <= it_obj["quantity"]:
                                cur_tr = conn.cursor()
                                
                                cur_tr.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (trans_qty, it_obj["id"]))
                                
                                dest_item = cur_tr.execute("SELECT id, quantity FROM items WHERE item_code = ? AND branch_id = ?", (it_obj["item_code"], to_id)).fetchone()
                                
                                if dest_item:
                                    cur_tr.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (trans_qty, dest_item["id"]))
                                else:
                                    cur_tr.execute("""
                                        INSERT INTO items (item_code, item_name, branch_id, quantity, buy_price, sale_price, avg_cost, favorite_rank)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                                    """, (it_obj["item_code"], it_obj["item_name"], to_id, trans_qty, it_obj["buy_price"], it_obj["sale_price"], it_obj["buy_price"]))
                                
                                details_str = f"تم نقل صنف: {it_obj['item_name']} (الكمية: {trans_qty}) من {from_b} إلى {to_b}"
                                cur_tr.execute("""
                                    INSERT INTO transfer_logs (from_branch_id, to_branch_id, items_details, status)
                                    VALUES (?, ?, ?, ?)
                                """, (from_id, to_id, details_str, "معلقة بانتظار استلام الكاشير"))
                                
                                conn.commit()
                                st.success(f"✅ تمت عملية التزويد ونقل البضاعة بنجاح من {from_b} إلى {to_b}!")
                                st.rerun()
                            else:
                                st.error("⚠️ الكمية المطلوبة غير متوفرة في مخزن المصدر!")
                else:
                    st.info(f"لا توجد أصناف في مخزن المصدر ({from_b}).")

    conn.close()
