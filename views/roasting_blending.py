import streamlit as st
import pandas as pd
from database import get_db_connection

def show_page():
    st.header("🥜 التحميص والخلط والمكسرات (حساب التكلفة وهامش الربح)")
    st.info("💡 إدارة عمليات خلط المكسرات وعمليات التحميص مع حساب متوسط التكلفة الفعلي وهامش الربح لمواكبة تذبذب أسعار المواد الخام.")

    conn = get_db_connection()

    # جلب المخزن الرئيسي حصرياً لعمليات التصنيع والخلط
    main_store_row = conn.execute("SELECT id, branch_name FROM branches WHERE branch_type='مخزن' LIMIT 1").fetchone()
    if not main_store_row:
        st.error("❌ تنبيه: لا يوجد مخزن رئيسي معرف في النظام! يرجى إنشاؤه من إدارة الفروع أولاً.")
        conn.close()
        return

    main_s_id = main_store_row["id"]
    store_items = conn.execute("SELECT id, item_code, item_name, quantity, buy_price, sale_price, avg_cost FROM items WHERE branch_id = ?", (main_s_id,)).fetchall()

    mix_tab, roast_tab = st.tabs(["🥜 خلط المكسرات (التكلفة وهامش الربح)", "🔥 التحميص (الفقد الوزني وهامش الربح)"])

    # --- تبويب خلط المكسرات ---
    with mix_tab:
        st.markdown("### 🥜 قسم خلط المكسرات والخامات")
        st.markdown("دمج عدة خامات بسعر تكلفتها الفعلية، وحساب **متوسط التكلفة الجديد** ومعرفة **هامش الربح** المتوقع للصنف الناتج.")
        
        if store_items:
            item_choices = {f"[{i['item_code']}] {i['item_name']} (متاح: {i['quantity']} كجم | تكلفة: {i['avg_cost'] or i['buy_price']} د.ل)": i for i in store_items}
            
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
                df_mix = pd.DataFrame(st.session_state["mix_list_state"])
                df_mix['total_item_cost'] = df_mix['qty'] * df_mix['cost']
                st.dataframe(df_mix[["code", "name", "qty", "cost", "total_item_cost"]], use_container_width=True)
                
                # حساب الإجماليات الأولية للخلطة
                tot_mix_cost = df_mix['total_item_cost'].sum()
                tot_mix_weight = df_mix['qty'].sum()
                pre_calculated_avg = tot_mix_cost / tot_mix_weight if tot_mix_weight > 0 else 0
                
                st.markdown(f"""
                    <div style="background: #f1f5f9; padding: 15px; border-radius: 10px; border: 1px solid #cbd5e1; margin-bottom: 15px;">
                        <h4 style="margin:0; color: #0f172a;">📊 ملخص الخلطة قبل الاعتماد:</h4>
                        <p style="margin: 5px 0;">⚖️ إجمالي الوزن الناتج المتوقع: <b>{tot_mix_weight:,.2f} كجم</b></p>
                        <p style="margin: 5px 0;">💰 إجمالي تكلفة الخامات الداخلة: <b>{tot_mix_cost:,.2f} د.ل</b></p>
                        <p style="margin: 0; color: #0284c7;">📈 متوسط تكلفة الكيلو الواحد (Avg Cost): <b>{pre_calculated_avg:,.2f} د.ل / كجم</b></p>
                    </div>
                """, unsafe_allow_html=True)

                with st.form("fin_mix_form"):
                    res_name = st.selectbox("اختر الصنف الناتج النهائي بعد الخلط (مثل: مكسرات مشكلة مسجلة):", [i['item_name'] for i in store_items])
                    
                    # البحث عن صنف معين لمعرفة سعر بيعه الحالي
                    target_item_obj = next((i for i in store_items if i['item_name'] == res_name), None)
                    current_sale_price = target_item_obj['sale_price'] if target_item_obj else 0.0
                    
                    new_sale_price = st.number_input("سعر بيع الكيلو المقترح للصنف الناتج (د.ل):", min_value=0.0, value=float(current_sale_price), step=0.5, format="%.2f")
                    
                    if st.form_submit_button("⚙️ اعتماد الخلطة وتحديث المخزن ومتوسط التكلفة وهامش الربح", type="primary"):
                        cur_mx = conn.cursor()
                        
                        # خصم الخامات من المخزن
                        for m in st.session_state["mix_list_state"]:
                            cur_mx.execute("UPDATE items SET quantity = quantity - ? WHERE branch_id = ? AND item_code = ?", 
                                         (m['qty'], main_s_id, m['code']))
                        
                        # إضافة الكمية وتحديث متوسط التكلفة وسعر البيع للصنف الناتج
                        cur_mx.execute("UPDATE items SET quantity = quantity + ?, avg_cost = ?, sale_price = ? WHERE branch_id = ? AND item_name = ?", 
                                     (tot_mix_weight, pre_calculated_avg, new_sale_price, main_s_id, res_name))
                        
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
        st.markdown("### 🔥 قسم التحميص (فقد الوزن التشغيلي وهامش الربح)")
        st.markdown("حساب تكلفة الفقد الوزني أثناء التحميص ومعرفة هامش الربح بدقة لتقييم ما إذا كان السعر الحالي يحتاج لزيادة أم لا.")
        
        if store_items:
            item_choices_roast = {f"[{i['item_code']}] {i['item_name']} (متاح: {i['quantity']} كجم | تكلفة: {i['avg_cost'] or i['buy_price']} د.ل)": i for i in store_items}
            
            with st.form("roast_form", clear_on_submit=True):
                sel_r = st.selectbox("اختر الصنف المراد تحميصه:", list(item_choices_roast.keys()), key="sel_roast_item")
                raw_w = st.number_input("الوزن الخام قبل التحميص (كجم):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
                roasted_w = st.number_input("الوزن الفعلي بعد التحميص (بعد الفقد):", min_value=0.0, value=0.0, step=0.1, format="%.2f")
                
                r_obj = item_choices_roast[sel_r]
                base_cost = r_obj['avg_cost'] if r_obj['avg_cost'] > 0 else r_obj['buy_price']
                
                st.info(f"ℹ️ تكلفة الشراء أو التكلفة السابقة للكيلو الخام هي: **{base_cost:,.2f} د.ل**")
                
                r_price = st.number_input("سعر بيع الصنف المحمص الجديد (د.ل):", min_value=0.0, value=float(r_obj['sale_price']), step=0.5, format="%.2f")
                
                if st.form_submit_button("🔥 اعتماد التحميص وحساب تكلفة الفقد والربح", type="primary"):
                    if raw_w > 0 and roasted_w > 0:
                        if r_obj['quantity'] < raw_w:
                            st.error("❌ الكمية الخام المطلوبة للتحميص أكبر من المتوفر في المخزن!")
                        else:
                            # المعادلة الحقيقية لتكلفة الكيلو بعد التحميص (بسبب الفقد الوزني)
                            # إجمالي قيمة الخام المدخل = (الوزن الخام * تكلفتها)
                            total_raw_value = raw_w * base_cost
                            # تكلفة الكيلو الفعلي بعد التحميص = إجمالي القيمة على الوزن الناتج الأقل
                            roasted_unit_cost = total_raw_value / roasted_w if roasted_w > 0 else base_cost
                            
                            # حساب هامش الربح
                            profit_val = r_price - roasted_unit_cost
                            profit_margin_pct = (profit_val / r_price * 100) if r_price > 0 else 0
                            
                            cur_r = conn.cursor()
                            # خصم الوزن الخام القديم
                            cur_r.execute("UPDATE items SET quantity = quantity - ?, avg_cost = ? WHERE branch_id = ? AND item_code = ?", 
                                         (raw_w, roasted_unit_cost, main_s_id, r_obj['item_code']))
                            # إضافة الوزن المحمص الجديد وتحديث السعر ومتوسط التكلفة الناتج عن الفقد
                            cur_r.execute("UPDATE items SET quantity = quantity + ?, sale_price = ?, avg_cost = ? WHERE branch_id = ? AND item_code = ?", 
                                         (roasted_w, r_price, roasted_unit_cost, main_s_id, r_obj['item_code']))
                            conn.commit()
                            
                            st.success(f"""
                                🎉 تمت عملية التحميص بنجاح!\n
                                - تكلفة الكيلو الفعلي بعد الفقد الوزني: {roasted_unit_cost:,.2f} د.ل\n
                                - هامش الربح المتوقع للكيلو: {profit_val:,.2f} د.ل ({profit_margin_pct:.1f}%)
                            """)
                            st.rerun()
                    else:
                        st.warning("⚠️ يرجى إدخال الأوزان بشكل صحيح.")
        else:
            st.warning("⚠️ لا توجد أصناف في المخزن الرئيسي للتحميص.")

    conn.close()
