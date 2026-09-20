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
    st.header("🔄 نظام تزويد الفروع والأرشيف (فواتير مجمعة)")
    st.info("💡 إنشاء فاتورة تزويد مجمعة تحتوي على عدة أصناف (من 1 إلى 15 صنفاً أو أكثر) وإرسالها للفرع كعهدَة مالية ومخزنية.")

    conn = get_db_connection()
    
    # تهيئة سلة أصناف التحويل المؤقتة في الجلسة
    if "transfer_cart" not in st.session_state:
        st.session_state["transfer_cart"] = []

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

    # التبويبات الأساسية
    transfer_mode = st.radio(
        "🎯 اختر القسم:",
        ["📦 إنشاء فاتورة تزويد جديدة (سلة الأصناف)", "📋 أرشيف فواتير التزويد المرسلة"],
        horizontal=True
    )

    st.markdown("---")

    # --- القسم الأول: سلة الفاتورة المجمعة وتزويد فرع ---
    if transfer_mode.startswith("📦"):
        col_target_b, col_notes = st.columns(2)
        with col_target_b:
            target_branch_name = st.selectbox("اختر الفرع المستهدف للإرسال:", [b["branch_name"] for b in branches if b["id"] != warehouse_id])
        with col_notes:
            transfer_notes = st.text_input("ملاحظات عامة على الفاتورة (اختياري):", value="")

        st.markdown("### 🛒 إضافة أصناف إلى فاتورة التزويد المجمعة")
        
        # جلب أصناف المخزن الرئيسي المتوفرة فقط
        items_in_warehouse = conn.execute("""
            SELECT id, item_code, item_name, quantity, sale_price, buy_price 
            FROM items 
            WHERE branch_id = ? AND quantity > 0
        """, (warehouse_id,)).fetchall()

        if items_in_warehouse:
            item_options = {f"{it['item_name']} (المتوفر: {it['quantity']} - السعر: {it['sale_price']} د.ل)": it for it in items_in_warehouse}
            
            with st.form("add_item_to_transfer_cart", clear_on_submit=True):
                col_i1, col_i2, col_i3 = st.columns([2, 1, 1])
                with col_i1:
                    sel_lbl = st.selectbox("اختر الصنف:", list(item_options.keys()))
                with col_i2:
                    selected_data = item_options[sel_lbl]
                    max_q = float(selected_data["quantity"])
                    t_qty = st.number_input("الكمية:", min_value=0.1, max_value=max_q, value=1.0, step=1.0)
                with col_i3:
                    st.write("")
                    st.write("")
                    add_btn = st.form_submit_button("➕ إضافة للسلة", use_container_width=True)
                
                if add_btn:
                    # التحقق إذا كان الصنف مضافاً مسبقاً في السلة
                    item_obj = item_options[sel_lbl]
                    exists = False
                    for c_it in st.session_state["transfer_cart"]:
                        if c_it["id"] == item_obj["id"]:
                            c_it["qty"] += t_qty
                            exists = True
                            break
                    if not exists:
                        st.session_state["transfer_cart"].append({
                            "id": item_obj["id"],
                            "code": item_obj["item_code"],
                            "name": item_obj["item_name"],
                            "price": float(item_obj["sale_price"]),
                            "buy_price": float(item_obj["buy_price"]),
                            "qty": float(t_qty)
                        })
                    st.success(f"تمت إضافة ({item_obj['item_name']}) إلى سلة الفاتورة بنجاح!")
                    st.rerun()
        else:
            st.warning(f"⚠️ المخزن الرئيسي ({warehouse_name}) خالي من الأصناف حالياً.")

        # عرض محتويات سلة الفاتورة الحالية
        st.markdown("### 📋 الأصناف المضافة للفاتورة الحالية")
        if st.session_state["transfer_cart"]:
            cart_df = pd.DataFrame(st.session_state["transfer_cart"])
            # تنسيق العرض للمستخدم
            display_cart_df = cart_df[["code", "name", "qty", "price"]].copy()
            display_cart_df.columns = ["كود الصنف", "اسم الصنف", "الكمية المطلوبة", "سعر البيع"]
            st.dataframe(display_cart_df, use_container_width=True, hide_index=True)

            col_act1, col_act2 = st.columns(2)
            with col_act1:
                if st.button("🚀 ترحيل واعتماد فاتورة التزويد للفرع", type="primary", use_container_width=True):
                    target_b_id = branch_dict[target_branch_name]
                    cur = conn.cursor()
                    
                    try:
                        # 1. تكوين تفاصيل الفاتورة النصية أو تخزينها
                        items_summary_list = []
                        for c_item in st.session_state["transfer_cart"]:
                            items_summary_list.append(f"{c_item['name']} ({c_item['qty']} كجم)")
                        
                        items_details_str = " | ".join(items_summary_list)
                        if transfer_notes:
                            items_details_str += f" -- ملاحظات: {transfer_notes}"

                        # 2. خصم الكميات من المخزن الرئيسي وإضافتها للفرع مباشرة
                        for c_item in st.session_state["transfer_cart"]:
                            # خصم من الرئيسي
                            cur.execute("UPDATE items SET quantity = quantity - ? WHERE id = ?", (c_item["qty"], c_item["id"]))
                            
                            # فحص هل الصنف موجود في الفرع المستهدف؟
                            target_item_row = cur.execute("""
                                SELECT id FROM items WHERE branch_id = ? AND item_name = ?
                            """, (target_b_id, c_item["name"])).fetchone()
                            
                            if target_item_row:
                                cur.execute("UPDATE items SET quantity = quantity + ? WHERE id = ?", (c_item["qty"], target_item_row["id"]))
                            else:
                                cur.execute("""
                                    INSERT INTO items (branch_id, item_code, item_name, quantity, buy_price, sale_price)
                                    VALUES (?, ?, ?, ?, ?, ?)
                                """, (target_b_id, c_item["code"], c_item["name"], c_item["qty"], c_item["buy_price"], c_item["price"]))

                        # 3. تسجيل الفاتورة في جدول السجلات والحركات لكي يراها الكاشير ويؤكدها
                        cur.execute("""
                            INSERT INTO transfer_logs (from_branch_id, to_branch_id, transfer_type, items_details, status)
                            VALUES (?, ?, ?, ?, ?)
                        """, (warehouse_id, target_b_id, "فاتورة تزويد مجمعة", items_details_str, "مع بانتظار تأكيد الكاشير"))
                        
                        conn.commit()
                        st.session_state["transfer_cart"] = [] # تفريغ السلة بعد الترحيل النجاح
                        st.success(f"✅ تم إصدار فاتورة التزويد المجمعة للفرع ({target_branch_name}) بنجاح وتم ترحيلها!")
                        st.rerun()
                    except Exception as ex:
                        conn.rollback()
                        st.error(f"❌ حدث خطأ أثناء ترحيل الفاتورة: {ex}")

            with col_act2:
                if st.button("🗑️ تفريغ السلة", use_container_width=True):
                    st.session_state["transfer_cart"] = []
                    st.rerun()
        else:
            st.info("🛒 السلة فارغة. قم بإضافة أصناف للفاتورة بالأعلى.")

    # --- القسم الثاني: أرشيف الفواتير المرسلة ---
    elif transfer_mode.startswith("📋"):
        st.subheader("📋 أرشيف فواتير وحركات التزويد السابقة")
        logs_df = pd.read_sql("""
            SELECT 
                transfer_logs.id AS 'رقم الفاتورة / الحركة',
                b1.branch_name AS 'المرسل (المخزن الرئيسي)',
                b2.branch_name AS 'الفرع المستهدف',
                transfer_logs.transfer_type AS 'نوع الفاتورة',
                transfer_logs.items_details AS 'تفاصيل الأصناف والكميات',
                transfer_logs.status AS 'حالة الاستلام',
                transfer_logs.transfer_date AS 'تاريخ الإصدار'
            FROM transfer_logs
            LEFT JOIN branches b1 ON transfer_logs.from_branch_id = b1.id
            LEFT JOIN branches b2 ON transfer_logs.to_branch_id = b2.id
            ORDER BY transfer_logs.id DESC
        """, conn)

        if not logs_df.empty:
            st.dataframe(logs_df, use_container_width=True, hide_index=True)
            excel_bytes = to_excel(logs_df)
            st.download_button(
                label="📥 تصدير الأرشيف إلى ملف Excel",
                data=excel_bytes,
                file_name=f"transfers_invoice_archive_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
        else:
            st.info("📌 لا توجد فواتير تزويد مسجلة في الأرشيف.")

    conn.close()
