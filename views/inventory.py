import streamlit as st
import pandas as pd
import os
from database import get_db_connection

def show_page():
    st.markdown("""
        <style>
        .rtl-container { direction: rtl !important; text-align: right !important; }
        .stButton > button { border-radius: 8px; font-weight: bold; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<h2 class="rtl-container">📦 إدارة المخزن والفروع وتوزيع البضاعة</h2>', unsafe_allow_html=True)
    st.markdown("---")
    
    conn = get_db_connection()
    
    # 🌟 التبويبات الرئيسية لإدارة الفروع والأصناف والتزويد
    tab_branches, tab_items, tab_transfer = st.tabs([
        "🏢 إدارة الفروع والمخازن", 
        "📋 تعريف وإدارة أصناف المخزن", 
        "🚚 تزويد ونقل البضائع بين الفروع"
    ])
    
    # ==========================================
    # 1. إدارة الفروع والمخازن
    # ==========================================
    with tab_branches:
        st.markdown("### ➕ إضافة فرع أو مخزن جديد")
        with st.form("add_branch_form_clean", clear_on_submit=True):
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
                        st.error("⚠️ هذا الفرع أو المخزن موجود مسبقاً.")
                else:
                    st.warning("⚠️ يرجى إدخال اسم الفرع.")

        st.markdown("### 📊 الفروع والمخازن المسجلة حالياً")
        branches_df = pd.read_sql("SELECT id AS 'رقم الفرع', branch_name AS 'اسم الفرع', branch_type AS 'النوع' FROM branches", conn)
        if not branches_df.empty:
            st.dataframe(branches_df, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد فروع مسجلة حتى الآن.")

    # ==========================================
    # 2. تعريف وإدارة أصناف المخزن
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
            
            with st.form("add_item_form_clean", clear_on_submit=True):
                col_i1, col_i2 = st.columns(2)
                i_code = col_i1.text_input("كود الصنف (الباركود):")
                i_name = col_i2.text_input("اسم الصنف:")
                
                col_i3, col_i4, col_i5, col_i6 = st.columns(4)
                i_qty = col_i3.number_input("الكمية الأولية:", min_value=0.0, value=0.0, step=1.0)
                i_buy = col_i4.number_input("سعر الشراء (د.ل):", min_value=0.0, value=0.0, step=0.5)
                i_sale = col_i5.number_input("سعر البيع (د.ل):", min_value=0.0, value=0.0, step=0.5)
                i_fav = col_i6.selectbox("إضافة للمفضلة؟", ["لا", "نعم"])
                
                # رفع صورة الصنف
                uploaded_img = st.file_uploader("صورة الصنف (اختياري - JPG/PNG):", type=["jpg", "png", "jpeg"])
                
                if st.form_submit_button("💾 حفظ الصنف في المخزن", type="primary"):
                    if i_code.strip() and i_name.strip():
                        try:
                            fav_val = 1 if i_fav == "نعم" else 0
                            cursor_item = conn.cursor()
                            cursor_item.execute("""
                                INSERT INTO items (item_code, item_name, branch_id, quantity, buy_price, sale_price, avg_cost, favorite_rank)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (i_code.strip(), i_name.strip(), target_branch_id, i_qty, i_buy, i_sale, i_buy, fav_val))
                            
                            # حفظ الصورة لو وجدت
                            if uploaded_img is not None:
                                os.makedirs("item_images", exist_ok=True)
                                img_path = os.path.join("item_images", f"{i_code.strip()}.jpg")
                                with open(img_path, "wb") as f:
                                    f.write(uploaded_img.getbuffer())
                                    
                            conn.commit()
                            st.success(f"✅ تمت إضافة الصنف ({i_name}) بنجاح!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"⚠️ حدث خطأ (ربما كود الصنف موجود مسبقاً في هذا الفرع): {e}")
                    else:
                        st.warning("⚠️ يرجى إدخال كود الصنف واسمه على الأقل.")

            st.markdown("### 📋 استعراض وتعديل أصناف المخازن")
            filter_branch = st.selectbox("فلترة العرض حسب المخزن:", ["الكل"] + list(b_dict.keys()), key="filter_branch_items")
            
            if filter_branch == "الكل":
                items_df = pd.read_sql("SELECT items.id, branches.branch_name AS 'الفرع', item_code AS 'الكود', item_name AS 'اسم الصنف', quantity AS 'الكمية', buy_price AS 'سعر الشراء', sale_price AS 'سعر البيع' FROM items JOIN branches ON items.branch_id = branches.id", conn)
            else:
                items_df = pd.read_sql("SELECT items.id, branches.branch_name AS 'الفرع', item_code AS 'الكود', item_name AS 'اسم الصنف', quantity AS 'الكمية', buy_price AS 'سعر الشراء', sale_price AS 'سعر البيع' FROM items JOIN branches ON items.branch_id = branches.id WHERE branches.branch_name = ?", conn, params=(filter_branch,))
                
            if not items_df.empty:
                st.dataframe(items_df, use_container_width=True, hide_index=True)
            else:
                st.info("لا توجد أصناف مسجلة في هذا المخزن.")

    # ==========================================
    # 3. تزويد ونقل البضائع بين الفروع
    # ==========================================
    with tab_transfer:
        st.markdown("### 🚚 تزويد ونقل بضاعة من المخزن الرئيسي إلى فرع بيع")
        
        branches_list = conn.execute("SELECT id, branch_name FROM branches").fetchall()
        b_map = {b["branch_name"]: b["id"] for b in branches_list}
        
        if len(b_map) < 2:
            st.warning("⚠️ يجب أن يكون لديك فرعين أو مخزن على الأقل لتمكين عملية نقل وبضائع التزويد.")
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
                    with st.form("transfer_item_form_clean", clear_on_submit=True):
                        sel_trans_item_str = st.selectbox("اختر الصنف المراد نقله:", list(s_items_dict.keys()))
                        trans_qty = st.number_input("الكمية المراد نقلها وتزويدها:", min_value=0.01, value=1.0, step=1.0)
                        
                        if st.form_submit_button("🚀 تنفيذ عملية النقل والتزويد", type="primary"):
                            it_obj = s_items_dict[sel_trans_item_str]
                            if trans_qty <= it_obj["quantity"]:
                                cur_tr = conn.cursor()
                                
                                # خصم الكمية من المصدر
                                cur_tr.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (trans_qty, it_obj["id"]))
                                
                                # التحقق هل الصنف موجود مسبقاً في فرع الاستلام أم لا؟
                                dest_item = cur_tr.execute("SELECT id, quantity FROM items WHERE item_code = ? AND branch_id = ?", (it_obj["item_code"], to_id)).fetchone()
                                
                                if dest_item:
                                    # تحديث الكمية في الفرع المستلم
                                    cur_tr.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (trans_qty, dest_item["id"]))
                                else:
                                    # إنشاء نسخة جديدة من الصنف في الفرع المستلم
                                    cur_tr.execute("""
                                        INSERT INTO items (item_code, item_name, branch_id, quantity, buy_price, sale_price, avg_cost, favorite_rank)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                                    """, (it_obj["item_code"], it_obj["item_name"], to_id, trans_qty, it_obj["buy_price"], it_obj["sale_price"], it_obj["buy_price"]))
                                
                                # تسجيل حركة التزويد في السجل لتظهر تنبيه للكاشير في الفرع المستلم
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
