import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("📦 إدارة المخزن والفروع والتزويد والتحويل")
    st.markdown("---")

    conn = get_db_connection()
    
    # جلب الفروع والمخازن من قاعدة البيانات
    branches = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ يرجى إضافة فروع أو مخازن أولاً من لوحة الإدارة.")
        conn.close()
        return

    branch_dict = {b["branch_name"]: b["id"] for b in branches}
    branch_names = list(branch_dict.keys())

    # القائمة المنسدلة الأساسية لاختيار الفرع أو المخزن للتحكم الكامل
    selected_branch = st.selectbox(
        "📍 اختر الفرع أو المخزن المطلوب إدارته وعرض مخزونه:", 
        branch_names, 
        key="main_inventory_branch_dropdown"
    )
    current_branch_id = branch_dict[selected_branch]

    st.markdown("---")

    # التقسيم الواضح للوحة التحكم بالمخزن
    tab_manage, tab_add, tab_transfer, tab_all_branches = st.tabs([
        f"📋 عرض وتعديل أرصدة وأسعار ({selected_branch})",
        "➕ إضافة صنف جديد (بالباركود أو اليدوي)",
        "🔄 تزويد وتحويل البضاعة بين الفروع",
        "🌐 متابعة أرصدة كافة الفروع والمخازن"
    ])

    # --- 1. قسم العرض والتعديل المباشر للفرع المختار ---
    with tab_manage:
        st.subheader(f"📋 الأصناف والأرصدة والأسعار الخاصة بـ: ({selected_branch})")
        
        items_df = pd.read_sql("""
            SELECT id, 
                   item_code AS 'كود الصنف', 
                   item_name AS 'اسم الصنف', 
                   quantity AS 'الكمية', 
                   buy_price AS 'سعر الشراء', 
                   sale_price AS 'سعر البيع', 
                   avg_cost AS 'متوسط التكلفة'
            FROM items 
            WHERE branch_id = ?
        """, conn, params=(current_branch_id,))

        if not items_df.empty:
            # حساب هامش الربح ونسبة الربح تلقائياً
            items_df['هامش الربح (د.ل)'] = items_df['سعر البيع'] - items_df['متوسط التكلفة']
            items_df['نسبة الربح %'] = ((items_df['هامش الربح (د.ل)'] / items_df['متوسط التكلفة']) * 100).fillna(0).round(1)

            edited_items_df = st.data_editor(
                items_df, 
                hide_index=True, 
                use_container_width=True,
                key=f"editor_branch_{current_branch_id}"
            )

            if st.button(f"💾 حفظ التعديلات للفرع ({selected_branch})", type="primary"):
                cur_up = conn.cursor()
                for _, row in edited_items_df.iterrows():
                    new_buy = float(row['سعر الشراء'])
                    cur_up.execute("""
                        UPDATE items 
                        SET item_code = ?, item_name = ?, quantity = ?, buy_price = ?, sale_price = ?, avg_cost = ? 
                        WHERE id = ?
                    """, (
                        str(row['كود الصنف']), 
                        str(row['اسم الصنف']), 
                        float(row['الكمية']), 
                        new_buy, 
                        float(row['سعر البيع']), 
                        new_buy, 
                        int(row['id'])
                    ))
                conn.commit()
                st.success("✅ تم حفظ التعديلات والأسعار ومتوسط التكلفة بنجاح!")
                st.rerun()
        else:
            st.info(f"لا توجد أصناف مسجلة في ({selected_branch}) حالياً.")

    # --- 2. قسم إضافة صنف جديد (بالباركود أو اليدوي مع خيار التعميم أو الفرع المختار) ---
    with tab_add:
        st.subheader("➕ إضافة صنف جديد (يدعم ماسح الباركود)")
        
        scope_choice = st.radio(
            "🎯 حدد نطاق الإضافة:", 
            [f"📍 إضافة للفرع المختار فقط ({selected_branch})", "🌐 تعميم لكافة الفروع والمخازن"], 
            horizontal=True
        )

        if "scanned_barcode" not in st.session_state: st.session_state["scanned_barcode"] = ""

        bc_input = st.text_input("كود الصنف / الباركود (امسح هنا):", key="inventory_barcode_input")
        if bc_input:
            st.session_state["scanned_barcode"] = bc_input.strip()

        current_bc = st.session_state["scanned_barcode"]

        if current_bc:
            check_b_id = current_branch_id if "فرع المختار" in scope_choice else branches[0]["id"]
            cur_chk = conn.cursor()
            existing = cur_chk.execute(
                "SELECT id, item_name, quantity, buy_price, sale_price FROM items WHERE branch_id = ? AND item_code = ?", 
                (check_b_id, current_bc)
            ).fetchone()

            if existing:
                st.warning(f"⚠️ الصنف موجود مسبقاً باسم: **{existing['item_name']}** (الكمية الحالية: {existing['quantity']})")
                add_q = st.number_input("الكمية المضافة:", min_value=0.0, value=0.0, step=0.5)
                new_b_price = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=float(existing["buy_price"]), step=0.5)
                new_s_price = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=float(existing["sale_price"]), step=0.5)

                if st.button("💾 تحديث الصنف الموجود", type="primary"):
                    target_ids = [current_branch_id] if "فرع المختار" in scope_choice else [b["id"] for b in branches]
                    for b_id in target_ids:
                        cur_chk.execute("""
                            UPDATE items 
                            SET quantity = quantity + ?, buy_price = ?, sale_price = ?, avg_cost = ?
                            WHERE branch_id = ? AND item_code = ?
                        """, (add_q, new_b_price, new_s_price, new_b_price, b_id, current_bc))
                    conn.commit()
                    st.success("✅ تم التحديث بنجاح!")
                    st.session_state["scanned_barcode"] = ""
                    st.rerun()
            else:
                st.success(f"✨ الكود ({current_bc}) غير موجود. أكمل البيانات أدناه لإضافته:")
                new_item_name = st.text_input("اسم الصنف الجديد *:")
                
                col_1, col_2 = st.columns(2)
                with col_1:
                    new_item_qty = st.number_input("الكمية الابتدائية:", min_value=0.0, value=1.0, step=0.5)
                    new_item_buy = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=0.0, step=0.5)
                with col_2:
                    new_item_sale = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=0.0, step=0.5)
                    new_item_exp = st.text_input("تاريخ الصلاحية (اختياري):", value="")

                if st.button("🚀 حفظ الصنف الجديد نهائياً", type="primary", use_container_width=True):
                    if not new_item_name.strip():
                        st.warning("⚠️ يرجى إدخال اسم الصنف!")
                    else:
                        cur_ins = conn.cursor()
                        target_ids = [current_branch_id] if "فرع المختار" in scope_choice else [b["id"] for b in branches]
                        
                        for b_id in target_ids:
                            cur_ins.execute("""
                                INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, expiry_date, no_expiry, favorite_rank)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                            """, (b_id, current_bc, new_item_name.strip(), new_item_qty, new_item_buy, new_item_sale, new_item_buy, new_item_exp))
                        
                        conn.commit()
                        st.session_state["scanned_barcode"] = ""
                        st.success(f"✅ تم إضافة الصنف ({new_item_name}) بنجاح تام!")
                        st.rerun()

        if st.button("🔄 مسح الباركود وإدخال غيره"):
            st.session_state["scanned_barcode"] = ""
            st.rerun()

    # --- 3. قسم تزويد وتحويل البضاعة بين الفروع والمخازن ---
    with tab_transfer:
        st.subheader("🔄 تزويد وتحويل البضاعة بين الفروع والمخزن")
        
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            from_b = st.selectbox("من (الفرع / المخزن المصدر):", branch_names, key="trans_from")
            from_id = branch_dict[from_b]
        with col_t2:
            to_b = st.selectbox("إلى (الفرع المستهدف):", branch_names, index=1 if len(branch_names) > 1 else 0, key="trans_to")
            to_id = branch_dict[to_b]

        if from_id == to_id:
            st.warning("⚠️ لا يمكن التحويل لنفس الفرع!")
        else:
            if "transfer_list" not in st.session_state: st.session_state["transfer_list"] = []

            source_items = conn.execute("SELECT id, item_code, item_name, quantity, buy_price, sale_price FROM items WHERE branch_id = ?", (from_id,)).fetchall()
            if source_items:
                item_choices = {f"[{it['item_code']}] {it['item_name']} (المتاح: {it['quantity']})": it for it in source_items}
                
                sel_it_str = st.selectbox("اختر الصنف المراد تحويله:", list(item_choices.keys()))
                tr_qty = st.number_input("الكمية المراد تحويلها:", min_value=0.01, value=1.0, step=0.5)

                chosen_item_data = item_choices[sel_it_str]

                if st.button("➕ إضافة لقائمة التحويل"):
                    if tr_qty > float(chosen_item_data["quantity"]):
                        st.error("⚠️ الكمية المطلوبة تتجاوز الرصيد المتاح في المصدر!")
                    else:
                        found_in_cart = False
                        for c in st.session_state["transfer_list"]:
                            if c["id"] == chosen_item_data["id"]:
                                c["qty"] += tr_qty
                                found_in_cart = True
                                break
                        if not found_in_cart:
                            st.session_state["transfer_list"].append({
                                "id": chosen_item_data["id"], "code": chosen_item_data["item_code"],
                                "name": chosen_item_data["item_name"], "qty": tr_qty,
                                "buy_price": chosen_item_data["buy_price"], "sale_price": chosen_item_data["sale_price"]
                            })
                        st.success("تمت الإضافة لقائمة التحويل.")

                if st.session_state["transfer_list"]:
                    st.markdown("#### الأصناف الجاهزة للتحويل:")
                    st.dataframe(pd.DataFrame(st.session_state["transfer_list"])[["code", "name", "qty"]], use_container_width=True, hide_index=True)
                    
                    if st.button("🚀 تنفيذ وترحيل التحويل نهائياً", type="primary", use_container_width=True):
                        cur_tr = conn.cursor()
                        for t_row in st.session_state["transfer_list"]:
                            # خصم من المصدر
                            cur_tr.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (t_row["qty"], t_row["id"]))
                            # إضافة للوجهة
                            dest_existing = cur_tr.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (to_id, t_row["code"])).fetchone()
                            if dest_existing:
                                cur_tr.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (t_row["qty"], dest_existing["id"]))
                            else:
                                cur_tr.execute("""
                                    INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, no_expiry, favorite_rank)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0)
                                """, (to_id, t_row["code"], t_row["name"], t_row["qty"], t_row["buy_price"], t_row["sale_price"], t_row["buy_price"]))

                        conn.commit()
                        st.session_state["transfer_list"] = []
                        st.success("✅ تمت عملية التحويل وتحديث مخزون الفروع بنجاح تام!")
                        st.rerun()
            else:
                st.info(f"لا توجد أصناف في ({from_b}) للتحويل منها.")

    # --- 4. متابعة أرصدة كافة الفروع ---
    with tab_all_branches:
        st.subheader("🌐 رصد ومتابعة مخزون كافة الفروع والمخازن")
        all_df = pd.read_sql("""
            SELECT b.branch_name AS 'الفرع أو المخزن', 
                   i.item_code AS 'كود الصنف', 
                   i.item_name AS 'اسم الصنف', 
                   i.quantity AS 'الكمية المتاحة', 
                   i.sale_price AS 'سعر البيع (د.ل)'
            FROM items i
            JOIN branches b ON i.branch_id = b.id
            ORDER BY b.branch_name, i.item_name
        """, conn)

        if not all_df.empty:
            st.dataframe(all_df, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد بيانات مسجلة للفروع بعد.")

    conn.close()
