import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("📦 المخزن والتزويد والتحويل (إدارة المخزون والفروع)")
    st.markdown("""
    > 💡 **إدارة المخزون الشاملة:** تحكم كامل عبر القوائم المنسدلة لاختيار الفروع والمخازن، تعديل الأسماء والأسعار والكميات لفرع معين أو للكل، والاستيراد الذكي والتحويل المباشر.
    """)

    conn = get_db_connection()
    
    # جلب كافة الفروع والمخازن من قاعدة البيانات
    branches = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ يرجى إضافة فروع أو مخازن أولاً من لوحة الإدارة.")
        conn.close()
        return

    # إنشاء قاموس الفروع لتعبئة القوائم المنسدلة (Drop-down lists)
    branch_dict = {b["branch_name"]: b["id"] for b in branches}
    branch_names_list = list(branch_dict.keys())

    # تقسيم الشاشة إلى تبويبات واضحة ومنظمة
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 عرض وتعديل أسماء وأسعار وأرصدة الفروع", 
        "➕ إضافة صنف جديد (بالباركود أو اليدوي)", 
        "📁 الاستيراد والتحديث الذكي (Excel)", 
        "🔄 تزويد وتحويل البضاعة بين الفروع",
        "🌐 متابعة أرصدة كافة الفروع والمخازن"
    ])

    # --- التبويب الأول: عرض وتعديل أسماء وأسعار وأرصدة الفروع (عبر القائمة المنسدلة) ---
    with tab1:
        st.subheader("📋 تعديل الأرصدة، الأسعار، والأصناف لفرع معين أو للكل")
        
        # دروب ليست لاختيار الفرع المراد عرض وتعديل أصنافه
        selected_view_branch = st.selectbox(
            "📍 اختر الفرع أو المخزن المطلوب عرضه وتعديله:", 
            branch_names_list, 
            key="view_edit_branch_dropdown"
        )
        target_view_b_id = branch_dict[selected_view_branch]

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
        """, conn, params=(target_view_b_id,))

        if not items_df.empty:
            # حساب هامش الربح ونسبة الربح تلقائياً
            items_df['هامش الربح (د.ل)'] = items_df['سعر البيع'] - items_df['متوسط التكلفة']
            items_df['نسبة الربح %'] = ((items_df['هامش الربح (د.ل)'] / items_df['متوسط التكلفة']) * 100).fillna(0).round(1)

            st.markdown(f"*(أنت تقوم الآن بتعديل بيانات فرع: **{selected_view_branch}**)*")
            edited_df = st.data_editor(
                items_df, 
                hide_index=True, 
                use_container_width=True,
                key=f"inv_editor_dropdown_{target_view_b_id}"
            )

            if st.button("💾 حفظ التعديلات المباشرة للفرع المختار", type="primary"):
                cur_up = conn.cursor()
                for _, row in edited_df.iterrows():
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
                st.success(f"✅ تم تحديث بيانات فرع ({selected_view_branch}) بنجاح تام!")
                st.rerun()
        else:
            st.info(f"لا توجد أصناف مسجلة في ({selected_view_branch}) حالياً.")

    # --- التبويب الثاني: إضافة صنف جديد (بالباركود أو اليدوي مع دروب ليست النطاق) ---
    with tab2:
        st.subheader("➕ إضافة صنف جديد عبر الباركود أو الإدخال اليدوي")
        st.info("💡 امسح الباركود بالكاميرا أو القارئ الضوئي في الحقل أدناه.")

        if "scanned_code" not in st.session_state: st.session_state["scanned_code"] = ""

        # دروب ليست لاختيار الفرع المستهدف للإضافة أو تعميمها للكل
        apply_scope_option = st.radio(
            "🎯 حدد نطاق إضافة الصنف:", 
            ["📍 فرع محدد (اختر من القائمة المنسدلة)", "🌐 تعميم لكافة الفروع والمخازن تلقائياً"], 
            horizontal=True
        )
        
        selected_target_branch_id = None
        if "فرع محدد" in apply_scope_option:
            chosen_b_name = st.selectbox("اختر الفرع المستهدف للإضافة:", branch_names_list, key="add_target_branch_dropdown")
            selected_target_branch_id = branch_dict[chosen_b_name]

        scanned_input = st.text_input("كود الصنف / الباركود (امسح هنا):", key="barcode_scan_field")
        if scanned_input:
            st.session_state["scanned_code"] = scanned_input.strip()

        current_code = st.session_state["scanned_code"]

        if current_code:
            # فحص ما إذا كان الكود موجوداً في الفرع المحدد أو المخزن الرئيسي
            check_b_id = selected_target_branch_id if selected_target_branch_id else branches[0]["id"]
            cur_chk = conn.cursor()
            existing_item = cur_chk.execute(
                "SELECT id, item_name, quantity, buy_price, sale_price FROM items WHERE branch_id = ? AND item_code = ?", 
                (check_b_id, current_code)
            ).fetchone()

            if existing_item:
                st.warning(f"⚠️ الصنف موجود مسبقاً باسم: **{existing_item['item_name']}** (الكمية الحالية: {existing_item['quantity']})")
                up_qty = st.number_input("الكمية المضافة:", min_value=0.0, value=0.0, step=0.5, key="add_exist_qty")
                up_buy = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=float(existing_item["buy_price"]), step=0.5, key="add_exist_buy")
                up_sale = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=float(existing_item["sale_price"]), step=0.5, key="add_exist_sale")

                if st.button("💾 تحديث رصيد وأسعار الصنف الموجود", type="primary"):
                    target_ids = [selected_target_branch_id] if selected_target_branch_id else [b["id"] for b in branches]
                    for b_id in target_ids:
                        cur_chk.execute("""
                            UPDATE items 
                            SET quantity = quantity + ?, buy_price = ?, sale_price = ?, avg_cost = ?
                            WHERE branch_id = ? AND item_code = ?
                        """, (up_qty, up_buy, up_sale, up_buy, b_id, current_code))
                    conn.commit()
                    st.success("✅ تم تحديث الصنف بنجاح!")
                    st.session_state["scanned_code"] = ""
                    st.rerun()
            else:
                st.success(f"✨ الكود ({current_code}) جديد. أدخل تفاصيل الصنف أدناه:")
                new_name = st.text_input("اسم الصنف الجديد *:", key="new_item_name_input")
                
                col_n1, col_n2 = st.columns(2)
                with col_n1:
                    new_qty = st.number_input("الكمية الابتدائية:", min_value=0.0, value=1.0, step=0.5, key="new_qty_input")
                    new_buy = st.number_input("سعر الشراء (د.ل):", min_value=0.0, value=0.0, step=0.5, key="new_buy_input")
                with col_n2:
                    new_sale = st.number_input("سعر البيع (د.ل):", min_value=0.0, value=0.0, step=0.5, key="new_sale_input")
                    new_expiry = st.text_input("تاريخ الصلاحية (اختياري):", value="", key="new_exp_input")

                if st.button("🚀 حفظ الصنف الجديد نهائياً", type="primary", use_container_width=True):
                    if not new_name.strip():
                        st.warning("⚠️ يرجى كتابة اسم الصنف أولاً!")
                    else:
                        cur_ins = conn.cursor()
                        target_ids = [selected_target_branch_id] if selected_target_branch_id else [b["id"] for b in branches]
                        
                        for b_id in target_ids:
                            chk_dupl = cur_ins.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (b_id, current_code)).fetchone()
                            if chk_dupl:
                                cur_ins.execute("""
                                    UPDATE items SET item_name = ?, quantity = quantity + ?, buy_price = ?, sale_price = ?, avg_cost = ?
                                    WHERE id = ?
                                """, (new_name.strip(), new_qty, new_buy, new_sale, new_buy, chk_dupl["id"]))
                            else:
                                cur_ins.execute("""
                                    INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, expiry_date, no_expiry, favorite_rank)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                                """, (b_id, current_code, new_name.strip(), new_qty, new_buy, new_sale, new_buy, new_expiry))
                        
                        conn.commit()
                        st.session_state["scanned_code"] = ""
                        st.success(f"✅ تم إضافة وحفظ الصنف ({new_name}) بنجاح تام!")
                        st.rerun()

        if st.button("🔄 مسح الكود وإدخال باركود جديد"):
            st.session_state["scanned_code"] = ""
            st.rerun()

    # --- التبويب الثالث: الاستيراد والتحديث الذكي (عبر القائمة المنسدلة للفرع أو الكل) ---
    with tab3:
        st.subheader("📁 الاستيراد والتحديث الذكي عبر ملف Excel / CSV")
        st.markdown("""
        > 📌 **تنبيه:** الأعمدة المطلوبة بالملف: `كود الصنف` | `اسم الصنف` | `سعر البيع` | `سعر الشراء` | `الكمية` | `تاريخ الصلاحية`  
        > *ميزة ذكية:* النظام يحدث الموجود بالكود دون تكرار ويضيف الجديد تلقائياً.
        """)

        import_scope_option = st.radio(
            "🎯 حدد نطاق استيراد وتحديث الملف:", 
            ["📍 فرع محدد (اختر من القائمة المنسدلة)", "🌐 تعميم وتحديث لكافة الفروع والمخازن"], 
            horizontal=True,
            key="import_scope_radio_main"
        )
        
        import_target_ids = []
        if "فرع محدد" in import_scope_option:
            chosen_import_b_name = st.selectbox("اختر الفرع المستهدف للاستيراد من القائمة:", branch_names_list, key="import_branch_dropdown")
            import_target_ids = [branch_dict[chosen_import_b_name]]
        else:
            import_target_ids = [b["id"] for b in branches]

        uploaded_excel = st.file_uploader("اختر ملف Excel أو CSV الخاص بالأصناف", type=["xlsx", "csv"], key="inv_file_uploader")

        if uploaded_excel is not None:
            try:
                df_imp = pd.read_csv(uploaded_excel) if uploaded_excel.name.endswith('.csv') else pd.read_excel(uploaded_excel)
                st.markdown("### 🔍 معاينة محتوى الملف المرفوع:")
                st.dataframe(df_imp.head(), use_container_width=True)

                if st.button("🚀 تنفيذ الاستيراد والتحديث الذكي للملف", type="primary"):
                    cur_imp = conn.cursor()
                    updated_count, inserted_count = 0, 0

                    for _, row in df_imp.iterrows():
                        if row.isna().all(): continue
                        code_val = str(row.get("كود الصنف", "")).strip()
                        name_val = str(row.get("اسم الصنف", "")).strip()
                        if name_val.lower() in ["nan", "none", ""]: continue

                        qty_val = float(row.get("الكمية", 0.0))
                        buy_val = float(row.get("سعر الشراء", 0.0))
                        sale_val = float(row.get("سعر البيع", 0.0))
                        exp_val = str(row.get("تاريخ الصلاحية", "")).strip()

                        for b_id in import_target_ids:
                            chk_item = cur_imp.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (b_id, code_val)).fetchone()
                            if chk_item:
                                cur_imp.execute("""
                                    UPDATE items SET item_name = ?, quantity = ?, buy_price = ?, sale_price = ?, avg_cost = ?, expiry_date = ?
                                    WHERE id = ?
                                """, (name_val, qty_val, buy_val, sale_val, buy_val, exp_val, chk_item["id"]))
                                updated_count += 1
                            else:
                                cur_imp.execute("""
                                    INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, expiry_date, no_expiry, favorite_rank)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                                """, (b_id, code_val, name_val, qty_val, buy_val, sale_val, buy_val, exp_val))
                                inserted_count += 1

                    conn.commit()
                    st.success(f"✅ تمت العملية بنجاح! تم تحديث ({updated_count}) صنفاً وإضافة ({inserted_count}) صنفاً جديداً.")
                    st.rerun()
            except Exception as e:
                st.error(f"خطأ أثناء قراءة الملف: {e}")

    # --- التبويب الرابع: تزويد وتحويل البضاعة بين الفروع (باستخدام دروب ليست المصدر والوجهة) ---
    with tab4:
        st.subheader("🔄 تزويد وتحويل البضاعة بين المخزن الرئيسي وفروع المؤسسة")
        
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            from_branch_name = st.selectbox("من (الفرع أو المخزن المصدر):", branch_names_list, key="transfer_from_dropdown")
            from_b_id = branch_dict[from_branch_name]
        with col_s2:
            to_branch_name = st.selectbox("إلى (الفرع المستهدف):", branch_names_list, index=1 if len(branch_names_list) > 1 else 0, key="transfer_to_dropdown")
            to_b_id = branch_dict[to_branch_name]

        if from_b_id == to_b_id:
            st.warning("⚠️ لا يمكن التحويل لنفس الفرع!")
        else:
            if "transfer_cart" not in st.session_state: st.session_state["transfer_cart"] = []

            source_items = conn.execute("SELECT id, item_code, item_name, quantity, buy_price, sale_price FROM items WHERE branch_id = ?", (from_b_id,)).fetchall()
            if source_items:
                item_options = {f"[{it['item_code']}] {it['item_name']} (المتاح: {it['quantity']})": it for it in source_items}
                
                col_add1, col_add2 = st.columns([2, 1])
                with col_add1: sel_item_str = st.selectbox("اختر الصنف للتحويل:", list(item_options.keys()), key="transfer_item_select")
                with col_add2: transfer_qty = st.number_input("الكمية المراد تحويلها:", min_value=0.01, value=1.0, step=0.5, key="transfer_qty_input")

                selected_item = item_options[sel_item_str]
                if st.button("➕ إضافة لقائمة التحويل"):
                    if transfer_qty > float(selected_item["quantity"]):
                        st.error("⚠️ الكمية المطلوبة أكبر من المتاح في الفرع المصدر!")
                    else:
                        exists = False
                        for c in st.session_state["transfer_cart"]:
                            if c["id"] == selected_item["id"]:
                                c["qty"] += transfer_qty
                                exists = True
                                break
                        if not exists:
                            st.session_state["transfer_cart"].append({
                                "id": selected_item["id"], "code": selected_item["item_code"],
                                "name": selected_item["item_name"], "qty": transfer_qty,
                                "buy_price": selected_item["buy_price"], "sale_price": selected_item["sale_price"]
                            })
                        st.success("تمت الإضافة لقائمة التحويل بنجاح.")

                if st.session_state["transfer_cart"]:
                    st.markdown("#### 📋 الأصناف الجاهزة للتحويل:")
                    st.dataframe(pd.DataFrame(st.session_state["transfer_cart"])[["code", "name", "qty"]], use_container_width=True, hide_index=True)
                    
                    col_t1, col_t2 = st.columns(2)
                    with col_t1:
                        if st.button("🚀 اعتماد وتنفيذ التحويل وخصم المصدر", type="primary", use_container_width=True):
                            cur_t = conn.cursor()
                            details_list = []
                            for t_item in st.session_state["transfer_cart"]:
                                cur_t.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (t_item["qty"], t_item["id"]))
                                dest_item = cur_t.execute("SELECT id FROM items WHERE branch_id = ? AND item_code = ?", (to_b_id, t_item["code"])).fetchone()
                                if dest_item:
                                    cur_t.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (t_item["qty"], dest_item["id"]))
                                else:
                                    cur_t.execute("""
                                        INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price, avg_cost, no_expiry, favorite_rank)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                                    """, (to_b_id, t_item["code"], t_item["name"], t_item["qty"], t_item["buy_price"], t_item["sale_price"], t_item["buy_price"]))
                                details_list.append(f"{t_item['name']} ({t_item['qty']})")

                            cur_t.execute("""
                                INSERT INTO transfer_logs (from_branch_id, to_branch_id, transfer_type, items_details, status)
                                VALUES (?, ?, ?, ?, ?)
                            """, (from_b_id, to_b_id, "تحويل بين الفروع", " | ".join(details_list), "مكتملة"))
                            conn.commit()
                            st.session_state["transfer_cart"] = []
                            st.success("✅ تم تنفيذ عملية التحويل وتحديث الأرصدة بنجاح تام!")
                            st.rerun()
                    with col_t2:
                        if st.button("🗑️ تفريغ قائمة التحويل", use_container_width=True):
                            st.session_state["transfer_cart"] = []
                            st.rerun()
            else:
                st.info(f"لا توجد أصناف متاحة في ({from_branch_name}) حالياً.")

    # --- التبويب الخامس: رؤية ومتابعة أرصدة كافة الفروع والمخازن ---
    with tab5:
        st.subheader("🌐 نظرة شاملة على مخزون وأرصدة كافة الفروع والمخازن")
        all_branches_items = pd.read_sql("""
            SELECT b.branch_name AS 'الفرع أو المخزن', 
                   i.item_code AS 'كود الصنف', 
                   i.item_name AS 'اسم الصنف', 
                   i.quantity AS 'الكمية المتاحة', 
                   i.sale_price AS 'سعر البيع (د.ل)'
            FROM items i
            JOIN branches b ON i.branch_id = b.id
            ORDER BY b.branch_name, i.item_name
        """, conn)

        if not all_branches_items.empty:
            st.dataframe(all_branches_items, use_container_width=True, hide_index=True)
        else:
            st.info("لا توجد بيانات مسجلة للفروع بعد.")

    conn.close()
