import streamlit as st
import pandas as pd
from datetime import datetime
from database import get_db_connection

def show_page():
    # 🌟 تنسيق CSS لضمان وضوح الخطوط والجداول
    st.markdown("""
        <style>
        .stDataFrame div, .stDataFrame span, .stDataFrame p, 
        div[data-testid="stTable"] *, th, td, 
        div[data-baseweb="select"] *, span, p, label, h3, h4 {
            color: #000000 !important;
            font-family: 'Tajawal', sans-serif !important;
            font-weight: 900 !important;
        }
        th {
            background-color: #94a3b8 !important;
            color: #000000 !important;
            font-size: 19px !important;
            text-align: right !important;
        }
        td {
            color: #000000 !important;
            font-size: 18px !important;
            background-color: #f8fafc !important;
            text-align: right !important;
        }
        .rtl-container { direction: rtl !important; text-align: right !important; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown('<h2 class="rtl-container">➕ الفائض، التوالف، والمرتجعات، وتعديل الأسعار</h2>', unsafe_allow_html=True)
    st.markdown("💡 إدارة التوالف، منتهيات الصلاحية، المرتجعات، تسجيل الفائض المخزني للفرع، وتعديل وتعميم الأسعار على كافة الفروع.")
    st.markdown("---")

    conn = get_db_connection()

    # جلب الفروع والمخازن
    branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ لا توجد فروع مسجلة في النظام.")
        conn.close()
        return

    b_dict = {b["branch_name"]: b["id"] for b in branches}

    # التبويبات الرئيسية الثلاثة
    tab1, tab2, tab3 = st.tabs([
        "🗑️ التوالف، منتهيات الصلاحية، والمرتجعات", 
        "➕ إضافة فائض مخزني لفرع معين", 
        "💲 تعديل وتعميم السعر على الفروع"
    ])

    # ==========================================
    # 1. التبويب الأول: التوالف والمرتجعات والإجماليات
    # ==========================================
    with tab1:
        st.markdown("### 🗑️ تسجيل وإدارة التوالف والمرتجعات")
        sel_branch_name = st.selectbox("اختر الفرع / المخزن:", list(b_dict.keys()), key="dam_branch_sel")
        b_id = b_dict[sel_branch_name]

        # 🌟 عرض الإجماليات في مكان بارز للرؤية العامة
        col_m1, col_m2, col_m3 = st.columns(3)
        dam_totals = conn.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN adjustment_type LIKE '%تالف%' OR adjustment_type LIKE '%منتهي%' THEN quantity ELSE 0 END), 0) as total_dam_qty,
                COALESCE(SUM(CASE WHEN adjustment_type LIKE '%تالف%' OR adjustment_type LIKE '%منتهي%' THEN loss_or_gain_value ELSE 0 END), 0) as total_dam_val,
                COALESCE(SUM(CASE WHEN adjustment_type LIKE '%صالح%' THEN quantity ELSE 0 END), 0) as total_ret_qty
            FROM stock_adjustments WHERE branch_id = ?
        """, (b_id,)).fetchone()

        with col_m1:
            st.metric(label="🗑️ إجمالي كمية التوالف والتالف", value=f"{dam_totals['total_dam_qty']:,.2f} كجم/قطعة")
        with col_m2:
            st.metric(label="💸 إجمالي قيمة خسائر التوالف", value=f"{dam_totals['total_dam_val']:,.2f} د.ل")
        with col_m3:
            st.metric(label="🔄 إجمالي المرتجعات السليمة", value=f"{dam_totals['total_ret_qty']:,.2f} كجم/قطعة")

        st.markdown("---")

        items_in_branch = conn.execute("""
            SELECT id, item_code, item_name, quantity, buy_price, avg_cost 
            FROM items WHERE branch_id = ?
        """, (b_id,)).fetchall()
        
        if items_in_branch:
            item_options = {f"[{it['item_code']}] {it['item_name']} (متاح: {it['quantity']})": it for it in items_in_branch}

            with st.form("damage_return_form", clear_on_submit=True):
                sel_item_label = st.selectbox("اختر الصنف:", list(item_options.keys()))
                selected_item = item_options[sel_item_label]
                
                col1, col2 = st.columns(2)
                qty = col1.number_input("الكمية:", min_value=0.01, value=1.0, step=1.0)
                
                adj_type = col2.selectbox("نوع الحركة (التصنيف):", [
                    "🗑️ تلف / كسر (خسارة تشغيلية)", 
                    "⏳ منتهي الصلاحية (خسارة تشغيلية)", 
                    "🔄 مرتجع زبون - صالح للبيع (يعود للمخزن)", 
                    "⚠️ مرتجع زبون - تالف (لا يعود للبيع)",
                    "🔄 إعادة صنف تالف/مُصلح إلى المخزن (إلغاء إتلاف)"
                ])
                
                notes = st.text_input("ملاحظات أو سبب الحركة (اختياري):", value="")
                
                submitted = st.form_submit_button("💾 اعتماد وتحديث المخزن وتسجيل الحركة", type="primary")
                
                if submitted:
                    if qty > 0:
                        cur = conn.cursor()
                        unit_cost = float(selected_item["avg_cost"]) if float(selected_item["avg_cost"]) > 0 else float(selected_item["buy_price"])
                        total_loss_value = qty * unit_cost
                        
                        if "صالح للبيع" in adj_type or "إعادة صنف تالف/مُصلح" in adj_type:
                            # زيادة الكمية في المخزن (سواء مرتجع صالح أو إصلاح تالف)
                            cur.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (qty, selected_item["id"]))
                            db_type = "إعادة صنف مُصلح للخدمة" if "إعادة صنف تالف/مُصلح" in adj_type else "مرتجع صالح للبيع"
                            # إذا كانت إعادة إصلاح، نضع القيمة بالسالب لخصمها من الخسائر المسجلة مسبقاً
                            if "إعادة صنف تالف/مُصلح" in adj_type:
                                total_loss_value = -total_loss_value
                        elif "تلف" in adj_type or "منتهي" in adj_type or "مرتجع زبون - تالف" in adj_type:
                            if float(selected_item["quantity"]) < qty:
                                st.error("❌ الكمية المراد إتلافها أكبر من المتوفر في المخزن!")
                                conn.close()
                                return
                            cur.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (qty, selected_item["id"]))
                            db_type = "تالف / منتهي الصلاحية / مرتجع تالف"
                        else:
                            db_type = "أخرى"

                        cur.execute("""
                            INSERT INTO stock_adjustments (branch_id, item_id, item_name, quantity, adjustment_type, loss_or_gain_value, notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (b_id, selected_item["id"], selected_item["item_name"], qty, db_type, total_loss_value, notes))
                        
                        conn.commit()
                        st.success("✅ تم تسجيل الحركة وتحديث المخزن وإظهار الإجماليات بنجاح!")
                        st.rerun()
                    else:
                        st.warning("⚠️ يرجى إدخال كمية صحيحة.")

        st.markdown("---")
        st.markdown("### 📊 سجل الحركات والتوالف لهذا الفرع")
        adjustments_df = pd.read_sql("""
            SELECT id AS 'رقم الحركة',
                   item_name AS 'اسم الصنف',
                   quantity AS 'الكمية',
                   adjustment_type AS 'نوع الحركة',
                   loss_or_gain_value AS 'قيمة الخسارة (د.ل)',
                   notes AS 'الملاحظات',
                   created_at AS 'التاريخ والوقت'
            FROM stock_adjustments
            WHERE branch_id = ?
            ORDER BY id DESC
        """, conn, params=(b_id,))

        if not adjustments_df.empty:
            st.dataframe(adjustments_df, use_container_width=True, hide_index=True)
        else:
            st.info("📭 لا توجد حركات توالف أو مرتجعات مسجلة لهذا الفرع.")

    # ==========================================
    # 2. التبويب الثاني: إضافة فائض مخزني لفرع معين
    # ==========================================
    with tab2:
        st.markdown("### ➕ إضافة فائض مخزني لفرع معين")
        sel_surplus_branch = st.selectbox("اختر الفرع لإضافة الفائض:", list(b_dict.keys()), key="surplus_branch_sel")
        b_surplus_id = b_dict[sel_surplus_branch]

        surplus_items = conn.execute("SELECT id, item_code, item_name, quantity FROM items WHERE branch_id = ?", (b_surplus_id,)).fetchall()
        
        if surplus_items:
            surplus_opts = {f"[{it['item_code']}] {it['item_name']} (الحالي: {it['quantity']})": it for it in surplus_items}

            with st.form("surplus_form", clear_on_submit=True):
                sel_sur_item_lbl = st.selectbox("اختر الصنف للفائض:", list(surplus_opts.keys()))
                sur_item_obj = surplus_opts[sel_sur_item_lbl]
                
                sur_qty = st.number_input("كمية الفائض المضافة:", min_value=0.01, value=1.0, step=1.0)
                sur_notes = st.text_input("سبب الفائض (اختياري):", value="جرد / فائض مخزني")
                
                if st.form_submit_button("💾 اعتماد وإضافة الفائض للمخزن", type="primary"):
                    if sur_qty > 0:
                        cur_s = conn.cursor()
                        cur_s.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (sur_qty, sur_item_obj["id"]))
                        cur_s.execute("""
                            INSERT INTO stock_adjustments (branch_id, item_id, item_name, quantity, adjustment_type, loss_or_gain_value, notes)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (b_surplus_id, sur_item_obj["id"], sur_item_obj["item_name"], sur_qty, "فائض مخزني", 0.0, sur_notes))
                        conn.commit()
                        st.success(f"✅ تمت إضافة الفائض ({sur_qty}) للصنف بنجاح!")
                        st.rerun()
                    else:
                        st.warning("⚠️ يرجى إدخال كمية صحيحة.")
        else:
            st.info("لا توجد أصناف في هذا الفرع.")

    # ==========================================
    # 3. التبويب الثالث: تعديل وتعميم السعر على الفروع
    # ==========================================
    with tab3:
        st.markdown("### 💲 تعديل وتعميم السعر على كافة الفروع")
        st.markdown("يمكنك تعديل سعر البيع لأي صنف وتعميمه فوراً على كافة الفروع والمخازن في النظام.")

        all_unique_items = conn.execute("SELECT DISTINCT item_code, item_name, sale_price FROM items").fetchall()
        if all_unique_items:
            item_price_opts = {f"[{it['item_code']}] {it['item_name']} (السعر الحالي: {it['sale_price']} د.ل)": it for it in all_unique_items}

            with st.form("price_generalize_form", clear_on_submit=True):
                sel_p_lbl = st.selectbox("اختر الصنف لتعديل وتعميم سعره:", list(item_price_opts.keys()))
                p_obj = item_price_opts[sel_p_lbl]

                new_general_price = st.number_input("سعر البيع الجديد (د.ل):", min_value=0.0, value=float(p_obj["sale_price"]), step=0.5)
                generalize_all = st.checkbox("تعميم هذا السعر على كافة الفروع والمخازن لنفس الصنف", value=True)

                if st.form_submit_button("💾 حفظ وتحديث السعر", type="primary"):
                    if new_general_price >= 0:
                        cur_p = conn.cursor()
                        if generalize_all:
                            cur_p.execute("UPDATE items SET sale_price = ? WHERE item_code = ? OR item_name = ?", 
                                          (new_general_price, p_obj["item_code"], p_obj["item_name"]))
                            conn.commit()
                            st.success(f"✅ تم تحديث وتعميم السعر الجديد ({new_general_price} د.ل) على كافة الفروع لهذا الصنف بنجاح!")
                        else:
                            st.info("يرجى تفعيل خيار تعميم السعر لتطبيق التعديل على جميع الفروع.")
                        st.rerun()
                    else:
                        st.warning("⚠️ يرجى إدخال سعر صحيح.")
        else:
            st.info("لا توجد أصناف مسجلة في النظام.")

    conn.close()
