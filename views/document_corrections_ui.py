"""Existing POS/transfer menu extension; compensating operations stay linked."""
_PAGE_ERROR_UI_REVISION = 71
import os,json,uuid,hashlib
from decimal import Decimal
from datetime import datetime,date
import streamlit as st
from database import get_db_connection
from views.dashboard import _validated_role
from views.branch_access import can_access_branch
from views.ui_common import back_button

def _error(error):
    if isinstance(error,(ValueError,PermissionError)):
        st.error(str(error));return
    response=getattr(error,'response',None)
    if response is not None:
        try:
            detail=response.json().get('detail','تعذر اعتماد الطلب')
            st.error(str(detail.get('message',detail) if isinstance(detail,dict) else detail));return
        except (ValueError,AttributeError):pass
    from views.page_guard import show_operation_error
    show_operation_error(error,announce=True,context='document_correction')

def _business_values(values):
    labels={'remaining':'المتبقي','source_quantity':'رصيد المصدر','target_quantity':'رصيد المستلم','source_avg':'متوسط تكلفة المصدر','target_avg':'متوسط تكلفة المستلم'}
    return '؛ '.join(labels[k]+': '+str(v) for k,v in values.items() if k in labels)

def show_page(kind):
    back_button(key='back_document_corrections_'+kind)
    if _validated_role() not in ('Admin','Super_Admin','Manager'):
        st.error('هذه الوظيفة للإدارة المخولة فقط.');return
    local=os.name=='nt';uid=st.session_state.get('user_id')
    if local:
        from offline_store import get_local_connection
        c=get_local_connection(queue_writes=False)
    else:c=get_db_connection()
    try:
        a=c.execute('SELECT id,role,branch_id,allowed_branches,is_active FROM users WHERE id=?',(uid,)).fetchone()
        if not a or not a['is_active'] or a['role'] not in ('Admin','Super_Admin','Manager'):
            st.error('تعذر اعتماد صلاحية الإدارة الحالية.');return
        branches=[dict(r) for r in c.execute('SELECT id,branch_name FROM branches ORDER BY id').fetchall() if a and can_access_branch(dict(a),r['id'])]
    finally:c.close()
    if not branches:st.warning('لا توجد فروع مصرح بها.');return
    st.header('مرتجع فاتورة مبيعات' if kind=='sale' else 'مرتجع وتصحيح وإلغاء تزويد')
    branch=st.selectbox('الفرع',branches,format_func=lambda b:b['branch_name'],key='correction_branch_'+kind)['id']
    number=st.text_input('رقم الفاتورة الأصلية' if kind=='sale' else 'رقم مستند التزويد',key='correction_source_'+kind).strip()
    key=kind+':'+str(branch)+':'+number
    if local:
        scope_conn=get_local_connection(queue_writes=False)
        try:scope_meta={r['key']:r['value'] for r in scope_conn.execute("SELECT key,value FROM local_meta WHERE key IN ('device_id','sync_generation')").fetchall()}
        finally:scope_conn.close()
        key+=':'+hashlib.sha256(json.dumps(scope_meta,sort_keys=True).encode()).hexdigest()
    cache='document_preview:'+hashlib.sha256(key.encode()).hexdigest()
    if st.button('عرض المستند الأصلي',key='correction_fetch_'+kind):
        try:
            if local:
                from offline_store import _request_with_auth_retry,get_local_connection
                lookup_number=number
                if kind=='transfer':
                    mapping_conn=get_local_connection(queue_writes=False)
                    try:
                        mapping=mapping_conn.execute("SELECT remote_id FROM erp_id_map WHERE table_name='transfer_logs' AND local_id=?",(number,)).fetchone()
                        local_record=mapping_conn.execute('SELECT id FROM transfer_logs WHERE CAST(id AS TEXT)=? AND to_branch_id=?',(number,branch)).fetchone()
                    finally:mapping_conn.close()
                    if mapping:lookup_number=str(mapping[0])
                    elif local_record:raise ValueError('مستند التزويد المحلي لم يصل للسيرفر بعد؛ انتظر ترحيله قبل تجهيز التصحيح.')
                response=_request_with_auth_retry('GET','/documents/corrections/preview',params={'kind':kind,'branch_id':branch,'number':lookup_number},timeout=20);response.raise_for_status();view=response.json()
                c=get_local_connection(queue_writes=False)
                try:c.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',(cache,json.dumps(view,ensure_ascii=False)));c.commit()
                finally:c.close()
            else:
                from views.document_corrections import preview
                from views.device_history_cancellation import bind_branch
                c=get_db_connection()
                try:bind_branch(c,branch);view=preview(c,uid,kind,branch,number)
                finally:c.rollback();c.close()
            st.session_state['correction_view_'+kind]=(key,view)
        except Exception as e:
            view=None
            if local:
                c=get_local_connection(queue_writes=False)
                try:row=c.execute('SELECT value FROM local_meta WHERE key=?',(cache,)).fetchone();view=json.loads(row[0]) if row else None
                finally:c.close()
            if view:st.warning('الاتصال غير متاح؛ هذه نسخة سابقة. يبقى أي طلب غير معتمد حتى التحقق المركزي.');st.session_state['correction_view_'+kind]=(key,view)
            else:_error(e)
    state=st.session_state.get('correction_view_'+kind)
    if state and state[0]==key:
        view=state[1];st.write('حالة المستند:',view.get('status',''));
        if local and kind=='transfer':st.caption('رقم المستند المركزي: '+str(view['source_number']))
        if kind=='sale':st.write('صافي الفاتورة الأصلية:',view.get('original_total',''),'— طريقة الدفع:',view.get('payment_method',''))
        st.dataframe([{'الصنف':x['name'],'الكمية الأصلية':x['quantity'],'المتبقي':x['remaining'],'سعر الفاتورة':x['price']} for x in view['items']],hide_index=True,use_container_width=True)
        mode='return'
        if kind=='transfer':mode=st.selectbox('العملية',['return','correct','cancel'],format_func=lambda x:{'return':'مرتجع كامل أو جزئي','correct':'تصحيح كميات أو أصناف','cancel':'إلغاء المتبقي بالكامل'}[x],key='correction_mode')
        full=st.checkbox('مرتجع كامل للمتبقي',key='correction_full_'+key) if mode=='return' else False
        quantities={};expiry={}
        for line in view['items']:
            remaining=float(line['remaining']);default=remaining if mode=='correct' else 0.0
            if mode=='cancel':quantities[line['key']]=line['remaining'];continue
            if full:quantities[line['key']]=line['remaining']
            else:quantities[line['key']]=str(st.number_input(('الكمية الصحيحة بعد التصحيح: ' if mode=='correct' else 'الكمية المرتجعة: ')+line['name'],min_value=0.0,value=default,step=.001,format='%.6f',key='correction_qty_'+key+'_'+line['key']))
            if kind=='sale' and st.checkbox('تحديد صلاحية الكمية المرتجعة: '+line['name'],key='correction_expiry_choice_'+key+'_'+line['key']):expiry[line['key']]=st.date_input('الصلاحية',min_value=date.today(),key='correction_expiry_'+key+'_'+line['key']).isoformat()
        extras=[]
        if kind=='transfer' and mode=='correct' and view.get('extra_candidates'):
            opts=view['extra_candidates'];selected=st.multiselect('أصناف إضافية لتصحيح الصنف الخطأ',opts,format_func=lambda x:x['name'],key='correction_extra_'+key)
            for item in selected:
                qty=st.number_input('الكمية الصحيحة للصنف الإضافي: '+item['name'],min_value=0.0,value=0.0,step=.001,format='%.6f',key='extra_qty_'+key+'_'+str(item['source_item_id']))
                extras.append({'source_item_id':item['source_item_id'],'quantity':str(qty)})
        treasury=None
        if kind=='sale' and view.get('payment_method')!='آجل (على الحساب)':
            treasuries=view.get('treasuries') or []
            if not treasuries:st.warning('لا توجد خزينة رد معتمدة في بيانات المستند.');return
            treasury=st.selectbox('خزينة رد المبلغ',treasuries,format_func=lambda x:x['treasury_name'],key='correction_treasury_'+key)['id']
        reason=st.text_input('سبب المرتجع أو التصحيح',key='correction_reason_'+key)
        verified=st.checkbox('راجعت المستند والكميات الفعلية واستلام أو نقل المرتجع ومصدر رد المبلغ',key='correction_verified_'+key)
        if local:st.info('يُحفظ الطلب أوفلاين دون صرف أو تعديل مخزون نهائي. يعتمد مرة واحدة بعد التحقق من السيرفر؛ لا تُسلّم مبلغًا قبل ظهور التأكيد.')
        if st.button('حفظ طلب المرتجع' if local else 'اعتماد المرتجع أو التصحيح',type='primary',key='correction_submit_'+kind,disabled=not reason.strip() or not verified):
            ident=st.session_state.setdefault('correction_request_'+key,str(uuid.uuid4()))
            body=dict(transaction_uuid=ident,actor_id=uid,device_id=None,sync_generation=None,kind=kind,branch_id=branch,source_number=view['source_number'],source_fingerprint=view['source_fingerprint'],quantities=quantities,mode=mode,reason=reason.strip(),stock_verified=verified,treasury_id=treasury,expiry_dates=expiry,extra_items=extras)
            try:
                if local:
                    from offline_store import get_local_connection,_SYNC_LOCK
                    from views.document_correction_client import queue_request
                    with _SYNC_LOCK:
                        c=get_local_connection(queue_writes=False)
                        try:c.execute('BEGIN IMMEDIATE');queue_request(c,body);c.commit()
                        except Exception:c.rollback();raise
                        finally:c.close()
                    st.success('حُفظ الطلب بانتظار التأكيد المركزي؛ راجع حالته أدناه.')
                else:
                    from views.document_corrections import apply
                    from views.device_history_cancellation import bind_branch
                    c=get_db_connection()
                    try:bind_branch(c,branch);result=apply(c,uid,body);c.commit()
                    except Exception:c.rollback();raise
                    finally:c.close()
                    st.success('تم الاعتماد: '+result['document_number'])
                    if result.get('amount') is not None:st.write('قيمة المرتجع:',result['amount'])
                st.session_state.pop('correction_view_'+kind,None);st.session_state.pop('correction_request_'+key,None)
            except Exception as e:_error(e)
    if local:
        from offline_store import get_local_connection,_SYNC_LOCK
        c=get_local_connection(queue_writes=False)
        try:
            rows=[dict(r) for r in c.execute("SELECT transaction_uuid,sync_status,sync_error,payload_json FROM erp_outbox WHERE source='document_correction' ORDER BY created_at DESC,rowid DESC LIMIT 30").fetchall() if json.loads(r['payload_json'])['actor_id']==uid]
            for r in rows:
                payload=json.loads(r.pop('payload_json'));st.write('المستند الأصلي:',payload['source_number'],'— الحالة:', 'بانتظار التأكيد' if r['sync_status']=='pending' else 'وصل التأكيد')
                if r.get('sync_error'):st.warning('لم يعتمد الطلب: '+str(r['sync_error']))
                saved=c.execute('SELECT value FROM local_meta WHERE key=?',('document_correction_receipt:'+r['transaction_uuid'],)).fetchone()
                if saved:
                    receipt=json.loads(saved[0]);st.write('أُلغي قبل الاعتماد' if receipt.get('cancelled') else 'اعتمد المستند: '+receipt.get('document_number',''))
                    if receipt.get('amount') is not None:st.write('قيمة المرتجع:',receipt['amount'])
                if r['sync_status']=='pending' and st.button('إلغاء طلب غير معتمد',key='cancel_intent_'+r['transaction_uuid']):
                    from views.document_correction_client import cancel_local_pending
                    try:
                        with _SYNC_LOCK:cancel_local_pending(c,r['transaction_uuid'])
                        st.success('تأكد إلغاء الطلب دون أثر مالي.');st.rerun()
                    except Exception as e:_error(e)
        finally:c.close()
    else:
        c=get_db_connection()
        try:
            history=c.execute('SELECT request_uuid,kind,source_id,actor_id,result_json,created_at FROM document_correction_requests WHERE branch_id=? ORDER BY created_at DESC LIMIT 30',(branch,)).fetchall()
            if history:
                st.subheader('سجل المستندات المرتبطة')
                st.dataframe([{'رقم المستند':json.loads(r['result_json']).get('document_number','طلب ملغى'),'الأصل':json.loads(r['result_json']).get('source_number',r['source_id']),'المستخدم':r['actor_id'],'الوقت':str(r['created_at'])} for r in history],hide_index=True,use_container_width=True)
                selected=st.selectbox('تفاصيل التصحيح',list(range(len(history))),format_func=lambda i:json.loads(history[i]['result_json']).get('document_number','طلب ملغى'),key='correction_history_details_'+kind)
                record=json.loads(history[selected]['result_json']);st.write('السبب:',record.get('reason',''))
                if record.get('changes'):st.dataframe([{'السطر':x['line_key'],'فرق الكمية':x['quantity_delta'],'فرق القيمة':x['value_delta'],'قبل':_business_values(x['before']),'بعد':_business_values(x['after'])} for x in record['changes']],hide_index=True,use_container_width=True)
        finally:c.close()
