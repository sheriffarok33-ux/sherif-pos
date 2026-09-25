import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("🥜 التحميص والخلط والمكسرات")
    st.info("💡 إدارة عمليات خلط المكسرات (بمتوسط التكلفة الحقيقي) وعمليات التحميص (بحساب الفقد الوزني بدقة).")

    conn = get_db_connection()

    # جلب المخزن الرئيسي حصرياً لعمليات التصنيع والخلط
    main_store_row = conn.execute("SELECT id, branch_name FROM branches WHERE branch_type='مخزن' LIMIT 1").fetchone()
    if not main_store_row:
        st.error("❌ تنبيه: لا يوجد مخزن رئيسي معرف في النظام! يرجى إنشاؤه من إدارة الفروع أولاً.")
        conn.close()
        return

    main_s_id = main_store_row["id"]
    store_items = conn.execute("SELECT item_code, item_name, quantity, buy_price, avg_cost FROM items WHERE branch_id = ? AND quantity > 0", (main_s_id,)).fetchall()

    mix_tab, roast_tab = st.tabs(["🥜 خلط المكسرات (دمج خامات وإنتاج صنف مشكل)", "🔥 التحميص (فقد وزني وتحديث السعر)"])

    # --- تبويب خلط المكسرات ---
    with mix_tab:
        st.markdown("### 🥜 قسم خلط المكسرات والخامات")
        st.markdown("يتم دمج عدة خامات (لوز، فستق..) بسعر تكلفتها، وخصمها من المخزن الرئيسي، وتحديث رصيد ومتوسط تكلفة الصنف الناتج.")
        
        if store_items:
            item_choices = {f"[{i['item_code']}] {i['item_name']} (متاح: {i['quantity']} كجم)": i for i in store_items}
            
            if "mix_list_state" not in st.session_state: 
                st.session_state["mix_list_state"] = []

            with st.form("mix_form", clear_on_submit=True):
                sel_c = st.selectbox("اختر الخام للخلط:", list(item_choices.keys()))
                mqty = st.number_input("الوزن المستخدم من الخامات (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
                if st.form_submit_button("➕ إضافة الخام لقائمة الخلط"):
                    if mqty > 0:
                        it_obj = item_choices[sel_c]
                        st.session_state["mix_list_state"].append({
                            "code": it_obj['item_code'], 
                            "name": it_obj['item_name'], 
                            "qty": mqty, 
                            "cost": it_obj['avg_cost'] if it_obj['avg_cost'] > 0 else it_obj['buy_price']
                        })
                        st.success("✅ تمت الإضافة لقائمة الخلط!")
                        st.rerun()
                    else:
                        st.warning("⚠️ يرجى إدخال كمية صحيحة.")

            if st.session_state["mix_list_state"]:
                st.markdown("#### 📋 خامات الخلطة الحالية:")
                st.dataframe(pd.DataFrame(st.session_state["mix_list_state"])[["code", "name", "qty", "cost"]], use_container_width=True)
                
                with st.form("fin_mix_form"):
                    res_name = st.selectbox("اختر الصنف الناتج النهائي بعد الخلط (مثل: مكسرات مشكلة):", [i['item_name'] for i in store_items])
                    if st.form_submit_button("⚙️ اعتماد الخلطة وخصم الخامات وتحديث صنف الناتج", type="primary"):
                        cur_mx = conn.cursor()
                        total_cost = sum([x['qty'] * x['cost'] for x in st.session_state["mix_list_state"]])
                        total_weight = sum([x['qty'] for x in st.session_state["mix_list_state"]])
                        new_avg = total_cost / total_weight if total_weight > 0 else 0
                        
                        # خصم الخامات من المخزن
                        for m in st.session_state["mix_list_state"]:
                            cur_mx.execute("UPDATE items SET quantity = quantity - ? WHERE branch_id = ? AND item_code = ?", 
                                         (m['qty'], main_s_id, m['code']))
                        
                        # إضافة الكمية وتحديث متوسط التكلفة للصنف الناتج
                        cur_mx.execute("UPDATE items SET quantity = quantity + ?, avg_cost = ? WHERE branch_id = ? AND item_name = ?", 
                                     (total_weight, new_avg, main_s_id, res_name))
                        
                        conn.commit()
                        st.session_state["mix_list_state"] = []
                        st.success("🎉 تمت عملية الخلط وحساب متوسط التكلفة وتحديث الأصناف بنجاح تام!")
                        st.rerun()

                if st.button("🗑️ تفريغ قائمة الخلط"):
                    st.session_state["mix_list_state"] = []
                    st.rerun()
        else:
            st.warning("⚠️ لا توجد أصناف متاحة في المخزن الرئيسي حالياً.")

    # --- تبويب التحميص ---
    with roast_tab:
        st.markdown("### 🔥 قسم التحميص (فقد الوزن التشغيلي)")
        st.markdown("عملية يفقد فيها الصنف وزناً أثناء التحميص (مثال: إدخال 10 كجم خام، لتخرج 9 كجم محمصة). يتم خصم الخام بالكامل وإضافة الوزن الفعلي الجديد.")
        
        if store_items:
            with st.form("roast_form", clear_on_submit=True):
                sel_r = st.selectbox("اختر الصنف المراد تحميصه:", list(item_choices.keys()), key="sel_roast_item")
                raw_w = st.number_input("الوزن الخام قبل التحميص (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
                roasted_w = st.number_input("الوزن الفعلي بعد التحميص (الوزن الجديد الناتج):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
                r_price = st.number_input("سعر بيع الصنف المحمص الجديد (د.ل):", min_value=0.0, value=0.0, step=0.5, format="%.2f")
                
                if st.form_submit_button("🔥 اعتماد التحميص وتحديث الأرصدة", type="primary"):
                    if raw_w > 0 and roasted_w > 0:
                        r_obj = item_choices[sel_r]
                        if r_obj['quantity'] < raw_w:
                            st.error("❌ الكمية الخام المطلوبة للتحميص أكبر من المتوفر في المخزن!")
                        else:
                            cur_r = conn.cursor()
                            # خصم الوزن الخام القديم
                            cur_r.execute("UPDATE items SET quantity = quantity - ? WHERE branch_id = ? AND item_code = ?", 
                                         (raw_w, main_s_id, r_obj['item_code']))
                            # إضافة الوزن المحمص الجديد وتحديث سعر البيع إن وجد
                            cur_r.execute("UPDATE items SET quantity = quantity + ?, sale_price = ? WHERE branch_id = ? AND item_code = ?", 
                                         (roasted_w, r_price, main_s_id, r_obj['item_code']))
                            conn.commit()
                            st.success("🎉 تمت عملية التحميص وتحديث أرصدة المخزن بنجاح!")
                            st.rerun()
                    else:
                        st.warning("⚠️ يرجى إدخال الأوزان بشكل صحيح.")
        else:
            st.warning("⚠️ لا توجد أصناف في المخزن الرئيسي للتحميص.")

    conn.close()
