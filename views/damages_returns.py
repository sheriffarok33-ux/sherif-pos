import streamlit as st
import pandas as pd
from datetime import datetime
from database import get_db_connection

def show_page():
    # 🌟 تنسيق CSS لضمان وضوح الخطوط باللون الأسود العريض
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

    st.markdown('<h2 class="rtl-container">🗑️ إدارة الفائض والتوالف، منتهيات الصلاحية، والمرتجعات</h2>', unsafe_allow_html=True)
    st.markdown("💡 من هنا يمكنك تسجيل المواد التالفة، منتهيات الصلاحية، أو مرتجعات الزبائن، وعزلها عن الأرباح اليومية لضمان دقة التقارير المالية.")
    st.markdown("---")

    conn = get_db_connection()

    # جلب الفروع والمخازن
    branches = conn.execute("SELECT id, branch_name FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ لا توجد فروع مسجلة في النظام.")
        conn.close()
        return

    b_dict = {b["branch_name"]: b["id"] for b in branches}
    sel_branch_name = st.selectbox("اختر الفرع / المخزن للتعامل مع التوالف أو المرتجعات:", list(b_dict.keys()))
    b_id = b_dict[sel_branch_name]

    # جلب أصناف الفرع المحددة
    items_in_branch = conn.execute("""
        SELECT id, item_code, item_name, quantity, buy_price, avg_cost 
        FROM items 
        WHERE branch_id = ?
    """, (b_id,)).fetchall()
    
    if not items_in_branch:
        st.info("📭 لا توجد أصناف مسجلة في هذا الفرع حالياً.")
        conn.close()
        return

    item_options = {f"[{it['item_code']}] {it['item_name']} (متاح: {it['quantity']} كجم)": it for it in items_in_branch}

    with st.form("damage_return_form", clear_on_submit=True):
        st.markdown("### 📝 تسجيل حركة جديدة (تالف / منتهي الصلاحية / مرتجع)")
        
        sel_item_label = st.selectbox("اختر الصنف:", list(item_options.keys()))
        selected_item = item_options[sel_item_label]
        
        col1, col2 = st.columns(2)
        qty = col1.number_input("الكمية:", min_value=0.01, value=1.0, step=1.0)
        
        adj_type = col2.selectbox("نوع الحركة (التصنيف):", [
            "🗑️ تلف / كسر (خسارة تشغيلية)", 
            "⏳ منتهي الصلاحية (خسارة تشغيلية)", 
            "🔄 مرتجع زبون - صالح للبيع (يعود للمخزن)", 
            "⚠️ مرتجع زبون - تالف (لا يعود للبيع)"
        ])
        
        notes = st.text_input("ملاحظات أو سبب الحركة (اختياري):", value="")
        
        submitted = st.form_submit_button("💾 اعتماد وتحديث المخزن وتسجيل الحركة", type="primary")
        
        if submitted:
            if qty > 0:
                cur = conn.cursor()
                unit_cost = float(selected_item["avg_cost"]) if float(selected_item["avg_cost"]) > 0 else float(selected_item["buy_price"])
                total_loss_value = qty * unit_cost
                
                # تحديد تأثير الكمية على المخزن بناءً على نوع الحركة
                if "صالح للبيع" in adj_type:
                    # مرتجع صالح للبيع: يزيد الكمية في المخزن ويعود للرصيد القابل للبيع
                    cur.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (qty, selected_item["id"]))
                    db_type = "مرتجع صالح للبيع"
                elif "تلف" in adj_type or "منتهي" in adj_type or "مرتجع زبون - تالف" in adj_type:
                    # تالف أو منتهي الصلاحية أو مرتجع تالف: يخصم نهائياً من المخزن ولا يعود للبيع
                    if float(selected_item["quantity"]) < qty:
                        st.error("❌ الكمية المراد إتلافها أكبر من المتوفر في المخزن!")
                        conn.close()
                        return
                    cur.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (qty, selected_item["id"]))
                    db_type = "تالف / منتهي الصلاحية / مرتجع تالف"
                else:
                    db_type = "أخرى"

                # تسجيل الحركة في جدول التوالف والمرتجعات المستقل
                cur.execute("""
                    INSERT INTO stock_adjustments (branch_id, item_id, item_name, quantity, adjustment_type, loss_or_gain_value, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (b_id, selected_item["id"], selected_item["item_name"], qty, db_type, total_loss_value, notes))
                
                conn.commit()
                st.success("✅ تم تسجيل الحركة وتحديث مخزون الفرع بنجاح تام!")
                st.rerun()
            else:
                st.warning("⚠️ يرجى إدخال كمية صحيحة.")

    st.markdown("---")
    st.markdown("### 📊 سجل التوالف والمرتجعات لهذا الفرع")
    
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
        st.info("📭 لا توجد حركات توالف أو مرتجعات مسجلة لهذا الفرع حتى الآن.")

    conn.close()
