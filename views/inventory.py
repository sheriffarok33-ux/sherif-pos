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
    
    # 🌟 التبويبات الرئيسية
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
            
            st.markdown("### 🏷️ قارئ الباركود وإدارة الأصناف")
            
            # تهيئة الذاكرة المؤقتة للباركود لتجنب ضياعه
            if "scanned_item_code" not in st.session_state:
                st.session_state["scanned_item_code"] = ""

            # استخدام Form منفصل للبحث بالباركود لضمان ثبات الرقم عند قراءته
            with st.form("barcode_search_form"):
                scanned_input = st.text_input("قم بمسح الباركود بالقارئ أو اكتبه واضغط Enter:", value=st.session_state["scanned_item_code"])
                search_btn = st.form_submit_button("🔍 بحث عن الصنف", type="primary")
                
                if search_btn and scanned_input.strip():
                    st.session_state["scanned_item_code"] = scanned_input.strip()
                    st.rerun()

            current_code = st.session_state["scanned_item_code"]

            if current_code:
                st.info(f"🎯 الكود النشط حالياً: **{current_code}**")
                
                if st.button("🔄 مسح الكود الحالي والبحث عن صنف آخر"):
                    st.session_state["scanned_item_code"] = ""
                    st.rerun()

                # التحقق هل الصنف مسجل مسبقاً في هذا الفرع؟
                existing_item = conn.execute(
                    "SELECT * FROM items WHERE item_code = ? AND branch_id = ?", 
                    (current_code, target_branch_id)
                ).fetchone()

                if existing_item:
                    st.success(f"✅ الصنف مسجل مسبقاً: **{existing_item['item_name']}**")
                    with st.form("update_existing_item_form"):
                        st.markdown("#### تحديث كمية أو سعر صنف موجود")
                        add_qty = st.number_input("إضافة كراتين أو قطع جديدة للمخزون:", min_value=0.0, value=0.0, step=1.0)
                        new_sale_price = st.number_input("تعديل سعر البيع:", min_value=0.0, value=float(existing_item['sale_price']), step=0.5)
                        
                        if st.form_submit_button("🔄 تحديث بيانات الصنف", type="primary"):
                            conn.execute(
                                "UPDATE items SET quantity = quantity + ?, sale_price = ? WHERE id = ?",
                                (add_qty, new_sale_price, existing_item['id'])
                            )
                            conn.commit()
                            st.success("✅ تم تحديث بيانات الصنف بنجاح!")
                            st.session_state["scanned_item_code"] = ""
                            st.rerun()
                else:
                    st.warning(f"⚠️ الكود ({current_code}) غير مسجل في هذا الفرع. يرجى إدخال تفاصيل الصنف الجديد:")
                    
                    with st.form("add_new_item_form", clear_on_submit=True):
                        i_name = st.text_input("اسم الصنف:")
                        
                        col_c1, col_c2 = st.columns(2)
                        pieces_per_carton = col_c1.number_input("كم قطعة داخل الكرتون؟", min_value=1, value=1, step=1)
                        cartons_count = col_c2.number_input("عدد الكراتين المضافة (الكمية):", min_value=0.0, value=1.0, step=1.0)
                        
                        total_pieces = cartons_count * pieces_per_carton
                        st.info(f"📦 إجمالي عدد القطع المضافة للمخزون تلقائياً: **{total_pieces} قطعة**")
                        
                        col_p1, col_p2 = st.columns(2)
                        box_buy_price = col_p1.number_input("سعر شراء الكرتون (د.ل):", min_value=0.0, value=0.0, step=0.5)
                        sale_price_piece = col_p2.number_input("سعر بيع القطعة المفردة (د.ل):", min_value=0.0, value=0.0, step=0.5)
                        
                        unit_buy_price = (box_buy_price / pieces_per_carton) if pieces_per_carton > 0 else 0.0
                        st.caption(f"💡 سعر تكلفة القطعة الواحدة محسوب تلقائياً: {unit_buy_price:,.2f} د.ل")
                        
                        i_fav = st.selectbox("إضافة لوحة المفضلة السريعة؟", ["لا", "نعم"])
                        uploaded_img = st.file_uploader("صورة الصنف (اختياري - JPG/PNG):", type=["jpg", "png", "jpeg"])
                        
                        if st.form_submit_button("💾 حفظ الصنف الجديد في المخزن", type="primary"):
                            if i_name.strip():
                                try:
                                    fav_val = 1 if i_fav == "نعم" else 0
                                    cursor_item = conn.cursor()
                                    cursor_item.execute("""
                                        INSERT INTO items (item_code, item_name, branch_id, quantity, buy_price, sale_price, avg_cost, favorite_rank)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                                    """, (current_code, i_name.strip(), target_branch_id, total_pieces, unit_buy_price, sale_price_piece, unit_buy_price, fav_val))
                                    
                                    if uploaded_img is not None:
                                        os.makedirs("item_images", exist_ok=True)
                                        img_path = os.path.join("item_images", f"{current_code}.jpg")
                                        with open(img_path, "wb") as f:
                                            f.write(uploaded_img.getbuffer())
                                            
                                    conn.commit()
                                    st.success(f"✅ تمت إضافة الصنف ({i_name}) بنجاح!")
                                    st.session_state["scanned_item_code"] = ""
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"⚠️ حدث خطأ أثناء الحفظ: {e}")
                            else:
                                st.warning("⚠️ يرجى إدخال اسم الصنف.")

            st.markdown("---")
            st.markdown("### 📋 جدول الأصناف المسجلة في المخزن")
            items_df = pd.read_sql("""
                SELECT items.id, branches.branch_name AS 'الفرع', 
                       item_code AS 'الكود', 
                       item_name AS 'اسم الصنف', 
                       quantity AS 'الكمية (قطع)', 
                       buy_price AS 'تكلفة القطعة', 
                       sale_price AS 'سعر البيع' 
                FROM items 
                JOIN branches ON items.branch_id = branches.id 
                WHERE branches.id = ?
            """, conn, params=(target_branch_id,))
            
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
                                """, (from_id, to_id, details_str, "معلقة بانتظار استلاستلام الكاشير"))
                                
                                conn.commit()
                                st.success(f"✅ تمت عملية التزويد ونقل البضاعة بنجاح من {from_b} إلى {to_b}!")
                                st.rerun()
                            else:
                                st.error("⚠️ الكمية المطلوبة غير متوفرة في مخزن المصدر!")
                else:
                    st.info(f"لا توجد أصناف في مخزن المصدر ({from_b}).")

    conn.close()
