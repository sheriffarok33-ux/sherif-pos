"""Explicit Super Admin reset preview, confirmation and per-device status."""
_PAGE_ERROR_UI_REVISION = 60
from views.page_guard import show_operation_error
import os
import streamlit as st
CHOICES={'الفواتير':'invoices','المبيعات وسجل البيع':'sales','الورديات':'shifts','الإيرادات':'revenues','المصروفات':'expenses','الأصناف ودفعاتها':'items','الكميات فقط':'quantities','إلغاء المعلقات غير المرسلة والسلة':'pending'}
LABELS={'invoices':'الفواتير','negative_sales_logs':'سجل البيع بالسالب','shift_closures':'الورديات','revenues':'الإيرادات','expenses':'المصروفات','items':'الأصناف','inventory_batches':'دفعات المخزون','document_registry':'أرشيف المستندات المرتبطة','treasury_movements':'حركات خزينة الفرع','financial_vouchers':'السندات المرتبطة','purchase_items':'بنود مشتريات مرتبطة','shift_settlement_adjustments':'تسويات الورديات','employee_financial_transactions':'حركات الموظفين المرتبطة','commitment_accruals':'استحقاقات مرتبطة','commitment_documents':'مستندات التزامات مرتبطة'}
def show_page():
    from views.dashboard import _validated_role
    if _validated_role()!='Super_Admin':st.error('التصفير متاح لـSuper Admin فقط');return
    st.title('تصفير بيانات الفرع')
    st.warning('التصفير يحذف البيانات المحددة وتوابعها المعروضة لهذا الفرع فقط. يصل الأمر إلى أجهزته عند الاتصال. لا تتغير هويات الأجهزة أو أرقام الفواتير المحجوزة، ولا يُعتبر تطبيق الأجهزة مكتملًا قبل إيصالاتها.')
    conn=None;actor=st.session_state.get('user_id')
    try:
        if os.name=='nt':
            from branch_auth import setup_branches,_request,_LAST_TOKEN
            if not _LAST_TOKEN:raise ValueError('يلزم تأكيد دخول Super Admin أونلاين')
            branches=setup_branches()
            def preview(bid,choices):return _request('/admin/branch-reset/preview',{'branch_id':bid,'choices':choices},_LAST_TOKEN)
            def apply(review,confirmation):return _request('/admin/branch-reset/execute',{k:review[k] for k in ('branch_id','choices','fingerprint','request_id')}|{'confirmation':confirmation},_LAST_TOKEN)
            def statuses(bid):return _request('/admin/branch-reset/status/'+str(bid),token=_LAST_TOKEN)['devices']
        else:
            from database import get_db_connection
            from control_services import write_audit_event
            from views import branch_reset_service as service
            conn=get_db_connection();branches=[dict(r) for r in conn.execute('SELECT id,branch_name FROM branches ORDER BY id').fetchall()]
            def preview(bid,choices):return service.preview(conn,actor,bid,choices)
            def apply(review,confirmation):
                result=service.perform(conn,actor,review['branch_id'],review['choices'],review['fingerprint'],confirmation,write_audit_event,review['request_id']);conn.commit();return result
            def statuses(bid):return service.status(conn,actor,bid)
        if '_branch_reset_notice' in st.session_state:st.success(st.session_state.pop('_branch_reset_notice'))
        names={int(b['id']):str(b['branch_name']) for b in branches}
        if not names:st.info('لا توجد فروع');return
        bid=st.selectbox('الفرع المطلوب فقط',list(names),format_func=lambda value:names[value],key='branch_reset_target')
        selected=st.multiselect('البيانات المطلوب تصفيرها',list(CHOICES),key='branch_reset_choices')
        choices=sorted({CHOICES[label] for label in selected})
        if 'pending' in choices:st.error('اختيار المعلقات يسمح بإلغاء السلة والحركات غير المرسلة، بما فيها حركات أجهزة كانت دون إنترنت. إلغاء فواتير غير مرسلة يتطلب اختيار الفواتير أيضًا. راجع ذلك قبل التأكيد.')
        if 'items' in choices and 'quantities' in choices:st.info('حذف الأصناف يشمل كمياتها؛ خيار الكميات لا يضيف حذفًا آخر.')
        reviewed=st.session_state.get('_branch_reset_preview')
        if reviewed and (reviewed['branch_id']!=bid or reviewed['choices']!=choices):
            st.session_state.pop('_branch_reset_preview',None);reviewed=None
        if st.button('معاينة ما سيُحذف دون تنفيذ',disabled=not choices):
            reviewed=preview(bid,choices);st.session_state['_branch_reset_preview']=reviewed
        if reviewed:
            st.subheader('معاينة الفرع: '+reviewed['branch_name'])
            st.caption(reviewed['notice'])
            st.dataframe([{'البيانات':LABELS.get(row['table'],'سجلات مرتبطة: '+row['table']),'الإجراء':'حذف' if row['action']=='delete' else 'تصفير الكمية','عدد السجلات':row['count']} for row in reviewed['plan']],hide_index=True,width='stretch')
            with st.form('branch_reset_confirm_'+reviewed['request_id']):
                confirmation=st.text_input('اكتب العبارة التالية حرفيًا: '+reviewed['confirmation'])
                aware=st.checkbox('راجعت الفرع والاختيارات والتوابع المعروضة وأوافق على تنفيذها على السيرفر وجميع أجهزة هذا الفرع')
                pending_aware=st.checkbox('أوافق صراحة على إلغاء السلة والحركات غير المرسلة المصرح بها') if 'pending' in choices else True
                submitted=st.form_submit_button('تأكيد تصفير الفرع المحدد',type='primary')
            if submitted:
                if not aware or not pending_aware or confirmation!=reviewed['confirmation']:st.error('لم يكتمل التأكيد الواضح للفرع والاختيارات؛ لم يُنفذ شيء')
                else:
                    result=apply(reviewed,confirmation)
                    st.session_state['_branch_reset_notice']='تم تنفيذ التصفير على السيرفر وحفظ الأمر '+result['reset_id']+'؛ تطبيق الأجهزة قيد المتابعة أدناه.'
                    st.session_state.pop('_branch_reset_preview',None);st.rerun()
        st.subheader('حالة تطبيق أوامر الفرع على الأجهزة')
        st.button('تحديث حالة الأجهزة',key='branch_reset_status_refresh')
        rows=statuses(bid)
        if rows:
            labels={'pending':'بانتظار الاتصال أو التحديث','applied':'تم التطبيق','failed':'فشل','superseded':'يشمله أمر أحدث؛ تابع الأمر الأحدث'}
            st.dataframe([{'الأمر':r['reset_id'],'رقم الجهاز':r['device_number'],'معرّف الجهاز':r['device_id'],'الحالة':labels.get(r['status'],r['status']),'السبب':r.get('error') or '', 'وقت إيصال التطبيق':str(r.get('applied_at') or '—')} for r in rows],hide_index=True,width='stretch')
        else:st.info('لا توجد أوامر تصفير محفوظة لهذا الفرع')
    except Exception as error:
        if conn is not None:conn.rollback()
        show_operation_error(error, announce=True, context='views/branch_reset_admin.py:66')
    finally:
        if conn is not None:conn.close()
