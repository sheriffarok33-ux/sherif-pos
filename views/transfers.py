import streamlit as st
import pandas as pd
import io
from datetime import datetime
from database import get_db_connection

def to_excel(df):
    """دالة تحويل أي جدول إلى ملف Excel جاهز للتنزيل"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Transfers_Archive')
    return output.getvalue()

def show_page():
    st.header("🔄 نظام تزويد الفروع والأرشيف الذكي")
    st.info("💡 تحويل البضائع والأصناف من المخزن الرئيسي إلى الفروع التشغيلية وتوثيق كافة الحركات في الأرشيف.")

    conn = get_db_connection()
    
    # جلب الفروع والمخازن
    branches = conn.execute("SELECT id, branch_name, branch_type FROM branches").fetchall()
    if not branches:
        st.warning("⚠️ يرجى إضافة فروع ومخازن أولاً.")
        conn.close()
        return

    branch_dict = {b["branch_name"]: b["id"] for b in branches}
    
    # تحديد المخزن الرئيسي
    warehouse_record = conn.execute("SELECT id, branch_name FROM branches WHERE branch_type = 'مخزن'").fetchone()
    if not warehouse_record:
        st.warning("⚠️ تنبيه: لا يوجد مخزن رئيسي معرف في نظام الفروع!")
        conn.close()
        return
    
    warehouse_id = warehouse_record["id"]
    warehouse_name = warehouse_record["branch_name"]

    # أزرار التبويبات الأفقية
    transfer_mode = st.radio(
        "🎯 اختر القسم:",
        ["🚚 تنفيذ عملية تزويد جديدة", "📋 أرشيف وسجل عمليات التزويد والتحويل"],
        horizontal=True
    )

    st.markdown("---")

    # --- القسم الأول: تنفيذ عملية تزويد جديدة ---
    if transfer_mode.startswith("🚚"):
        st.subheader(f"📦 سحب بضاعة من ({warehouse_name}) وتزويد فرع")

        # جلب أصناف المخزن الرئيسي المتوفرة فقط
        items_in_warehouse = conn.execute("""
            SELECT id, item_code, item_name, quantity, sale_price, buy_price 
            FROM items 
            WHERE branch_id = ? AND quantity > 0
        """, (warehouse_id,)).fetchall()

        if not items_in_warehouse:
            st.warning(f"⚠️ المخزن الرئيسي ({warehouse_name}) خالي تماماً من الأصناف أو رصيدها صفر!")
            conn.close()
            return

        item_options = {f"{it['item_name']} (المتوفر: {it['quantity']} - الكود: {it['item_code'] or 'بدون'})": it for it in items_in_warehouse}

        with st.form("transfer_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                selected_item_label = st.selectbox("اختر الصنف المراد تحويله:", list(item_options.keys()))
                target_branch_name = st.selectbox("اختر الفرع المستهدف للإرسال:", [b["branch_name"] for b in branches if b["id"] != warehouse_id])
            with col2:
                selected_item_data = item_options[selected_item_label]
                max_avail = selected_item_data["quantity"]
                transfer_qty = st.number_input(f"الكمية المراد تحويلها (الحد الأقصى: {max_avail}):", min_value=0.1, max_value=float(max_avail), value=1.0, step=1.0)
                notes = st.text_input("ملاحظات عملية التحويل (اختياري):", value="")

            submit_transfer = st.form_submit_button("🚀 اعتماد وتنفيذ عملية التزويد", type="primary", use_container_width=True)

            if submit_transfer:
                if transfer_qty <= 0:
                    st.error("⚠️ يرجى إدخال كمية صحيحة أكبر من الصفر!")
                else:
                    target_b_id = branch_dict[target_branch_name]
                    cur = conn.cursor()
                    
                    try:
                        # 1. خصم الكمية من المخزن الرئيسي
                        cur.execute("""
                            UPDATE items SET quantity = quantity - ? WHERE id = ?
                        """, (transfer_qty, selected_item_data["id"]))

                        # 2. التحقق هل الصنف موجود مسبقاً في الفرع المستهدف؟
                        existing_in_target = cur.execute("""
                            SELECT id, quantity FROM items 
                            WHERE branch_id = ? AND item_name = ?
                        """, (target_b_id, selected_item_data["item_name"])).fetchone()

                        if existing_in_target:
                            # تحديث الكمية في الفرع
                            cur.execute("""
                                UPDATE items SET quantity = quantity + ? WHERE id = ?
                            """, (transfer_qty, existing_in_target["id"]))
                        else:
                            # إضافته كصنف جديد في الفرع المستهدف بنفس البيانات
                            cur.execute("""
                                INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (
                                target_b_id, 
                                selected_item_data["item_code"], 
                                selected_item_data["item_name"], 
                                transfer_qty, 
                                selected_item_data["buy_price"], 
                                selected_item_data["sale_price"]
                            ))

                        # 3. توثيق العملية في أرشيف الحركات (transfer_logs)
                        item_detail_str = f"الصنف: {selected_item_data['item_name']} | الكمية: {transfer_qty} | ملاحظات: {notes}"
                        cur.execute("""
                            INSERT INTO transfer_logs (from_branch_id, to_branch_id, transfer_type, items_details, status)
                            VALUES (?, ?, ?, ?, 'مكتملة')
                        """, (warehouse_id, target_b_id, "تزويد فرع", item_detail_str))

                        conn.commit()
                        st.success(f"✅ تم تزويد الفرع ({target_branch_name}) بالصنف بنجاح وتم خصمها من المخزن الرئيسي!")
                        st.rerun()
                    except Exception as e:
                        conn.rollback()
                        st.error(f"❌ حدث خطأ أثناء تنفيذ عملية التحويل: {e}")

    # --- القسم الثاني: أرشيف وسجل عمليات التزويد ---
    elif transfer_mode.startswith("📋"):
        st.subheader("📋 أرشيف حركات التحويل والتزويد السابقة")

        logs_df = pd.read_sql("""
            SELECT 
                transfer_logs.id AS 'رقم الحركة',
                b1.branch_name AS 'من (المرسل)',
                b2.branch_name AS 'إلى (المستقبل)',
                transfer_logs.transfer_type AS 'نوع الحركة',
                transfer_logs.items_details AS 'تفاصيل الأصناف والكميات',
                transfer_logs.status AS 'الحالة',
                transfer_logs.transfer_date AS 'تاريخ ووقت التحويل'
            FROM transfer_logs
            LEFT JOIN branches b1 ON transfer_logs.from_branch_id = b1.id
            LEFT JOIN branches b2 ON transfer_logs.to_branch_id = b2.id
            ORDER BY transfer_logs.id DESC
        """, conn)

        if not logs_df.empty:
            st.dataframe(logs_df, use_container_width=True, hide_index=True)

            # زر تصدير الأرشيف إلى إكسيل
            excel_bytes = to_excel(logs_df)
            st.download_button(
                label="📥 تصدير أرشيف التزويد إلى ملف Excel",
                data=excel_bytes,
                file_name=f"transfers_archive_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.info("📌 لا توجد عمليات تزويد مسجلة في الأرشيف حتى الآن.")

    conn.close()
