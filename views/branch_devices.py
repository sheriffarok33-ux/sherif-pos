"""Super Admin device registry; branch moves require the workstation's approval."""
_PAGE_ERROR_UI_REVISION = 60
from views.page_guard import show_operation_error
import os
import streamlit as st

def show_page():
    from views.dashboard import _validated_role
    if _validated_role() not in ('Super_Admin','Admin','Manager'):st.error('هذه الشاشة متاحة للإدارة المخولة فقط');return
    st.title('إدارة أجهزة الفروع')
    from views.update_distribution import render_distribution
    render_distribution()
    actor=st.session_state.get('user_id');conn=None
    try:
        if os.name=='nt':
            from branch_auth import admin_device_registry,setup_branches,admin_request_device_change,admin_cancel_device_change,admin_request_device_action,admin_prepare_device
            registry=admin_device_registry();branches=setup_branches()
            save=admin_request_device_change;cancel=admin_cancel_device_change;action_request=admin_request_device_action;add=admin_prepare_device
        else:
            from database import get_db_connection
            from views.device_registry import list_registered,request_change,cancel_change,register_device
            conn=get_db_connection();registry=list_registered(conn,actor)
            branches=[dict(r) for r in conn.execute('SELECT id,branch_name,is_active FROM branches ORDER BY id').fetchall()]
            from views.device_lifecycle import request_action
            def add(device_id,bid,number,name):
                result=register_device(conn,actor,device_id,bid,number,name);conn.commit();return result
            def action_request(device_id,action,confirm):
                result=request_action(conn,actor,device_id,action,confirm);conn.commit();return result
            def save(device_id,bid,number,name):
                result=request_change(conn,actor,device_id,bid,number,name);conn.commit();return result
            def cancel(command_id):
                result=cancel_change(conn,actor,command_id);conn.commit();return result
        if '_device_registry_notice' in st.session_state:
            notice=st.session_state.pop('_device_registry_notice')
            level=st.session_state.pop('_device_registry_notice_level','success')
            st.warning(notice) if level=='warning' else st.success(notice)
        devices=registry.get('devices',[]);changes=registry.get('changes',[])
        historical=registry.get('historical_devices',[])
        if historical:
            with st.expander('السجل التاريخي للأجهزة — محررة لإعادة الاستخدام'):
                st.caption('السجلات المالية محفوظة؛ هذه الأجهزة لا تحجز أرقامًا ولا تنتظر تحديثات.')
                st.dataframe([{'الهوية':d['device_id'],'الفرع السابق':d['branch_id'],
                    'الرقم السابق':d['device_number'],'الحالة':'محرر لإعادة الاستخدام'} for d in historical],hide_index=True,width='stretch')
        if any(d.get('registration_state')=='unregistered' for d in devices):
            show_removed=st.checkbox('عرض الأجهزة المحذوف تسجيلها وسجلها التاريخي',key='show_unregistered_devices')
            if not show_removed:devices=[d for d in devices if d.get('registration_state')!='unregistered']
        labels={int(b['id']):str(b['branch_name']) for b in branches}
        for d in devices:labels.setdefault(int(d['branch_id']),'فرع #'+str(d['branch_id']))
        if not labels:st.info('لا توجد فروع مسجلة');return
        requested=st.session_state.pop('_device_branch_request',None)
        if requested in labels:st.session_state['device_admin_branch']=requested
        branch=st.selectbox('الفرع',list(labels),format_func=lambda bid:labels[bid],key='device_admin_branch')
        scoped=[d for d in devices if int(d['branch_id'])==branch]
        from views.update_distribution import render_release_summary,device_status_rows
        render_release_summary(registry)
        if scoped:
            st.dataframe([{'رقم الجهاز':d['device_number'],'Device ID':d['device_id'],'حالة التسجيل':'مسجل ونشط' if d['is_active'] else 'غير نشط — السجل محفوظ','آخر اتصال':d.get('last_seen_at') or 'لم يُسجل اتصال'} for d in scoped],hide_index=True,width='stretch')
            st.dataframe(device_status_rows(scoped),hide_index=True,width='stretch')
        scoped.sort(key=lambda d:(not bool(d['is_active']),int(d['device_number']),d['device_id']))
        active_count=sum(bool(d['is_active']) for d in scoped)
        st.caption(f'عدد أجهزة الفرع: {len(scoped)} — النشطة: {active_count} — غير النشطة: {len(scoped)-active_count}')
        pending={r['device_id']:r for r in changes if r['status'] in ('pending','awaiting_local_confirmation')}
        states={'pending':'بانتظار اعتماد الجهاز','awaiting_local_confirmation':'بانتظار إيصال التطبيق المحلي','failed':'فشل'}
        st.caption('أرقام الأجهزة تبدأ من1 لكل فرع، وعدد الأجهزة غير محدود. الهوية الداخلية ثابتة.')
        if _validated_role() in ('Super_Admin','Manager'):
            with st.expander('إضافة جهاز جديد'):
                st.caption('أدخل Device ID الظاهر في تجهيز جهاز Windows نفسه؛ لا تُنشئ أو تنسخ هوية جهاز آخر. يُحجز الرقم ثم يستكمل Super Admin التجهيز على ذلك الجهاز.')
                with st.form('device_admin_add_'+str(branch)):
                    new_id=st.text_input('Device ID للجهاز الجديد',max_chars=36)
                    new_name=st.text_input('اسم الجهاز الجديد',max_chars=80)
                    new_number=st.number_input('رقم الجهاز الجديد داخل الفرع',min_value=1,max_value=999999999,value=1,step=1)
                    confirmed_add=st.checkbox('أؤكد أن المعرّف مأخوذ من الجهاز الجديد نفسه')
                    add_pressed=st.form_submit_button('إضافة الجهاز')
                if add_pressed:
                    if not confirmed_add:st.error('أكد هوية الجهاز الجديد أولًا')
                    else:
                        result=add(new_id.strip(),branch,new_number,new_name.strip());st.session_state['_device_registry_notice']=result['message'];st.rerun()
        st.caption('السجلات غير النشطة تاريخية؛ لا تحجز الرقم ولا تعني وجود جهاز نشط مكرر. لا تُحذف الفواتير عند إلغاء التسجيل.')
        if not scoped:st.info('لا توجد أجهزة مسجلة لهذا الفرع')
        else:
            st.dataframe([{'رقم الجهاز':d['device_number'],'اسم الجهاز':d.get('device_name') or 'غير مسمى','المعرّف':d['device_id'],'الحالة':('نشط' if d.get('credential_ready',True) else 'بانتظار التجهيز المحلي') if d['is_active'] else 'ملغى / تاريخي','آخر اتصال':d.get('last_seen_at') or 'غير متوفر','فواتير مؤكدة':d.get('confirmed_invoice_count',0),'فواتير لم تُسوّ':d.get('unsettled_confirmed_invoices',0),'فواتير معلقة بآخر اتصال':d.get('pending_invoices') if d.get('last_seen_at') else 'غير معروف','عمليات معلقة بآخر اتصال':d.get('pending_operations') if d.get('last_seen_at') else 'غير معروف','التعديل':states.get(pending.get(d['device_id'],{}).get('status'),'لا يوجد تعديل معلق')} for d in scoped],hide_index=True,use_container_width=True)
            if st.session_state.get('device_admin_selected') not in {d['device_id'] for d in scoped}:
                st.session_state.pop('device_admin_selected',None)
            chosen=st.selectbox('الجهاز المراد تعديل بياناته',[d['device_id'] for d in scoped],format_func=lambda identity:next(str(d['device_number'])+' — '+('نشط' if d['is_active'] else 'تاريخي غير نشط')+' — '+d['device_id'] for d in scoped if d['device_id']==identity),key='device_admin_selected')
            device=next(d for d in scoped if d['device_id']==chosen)
            if _validated_role()!='Admin':render_device_invoices(device,actor,conn)
            if not device['is_active'] and device.get('registration_state')!='unregistered' and _validated_role() in ('Super_Admin','Manager'):
                st.subheader('حذف تسجيل الجهاز القديم')
                st.caption('يحذف تسجيله من قائمة أجهزة الفرع ويبطل اعتماده القديم، ثم يسمح بإضافة نفس المعرّف لفرع آخر. تبقى الفواتير والمبيعات والسجلات التاريخية محفوظة.')
                with st.form('unregister_old_'+chosen):
                    remove_id=st.text_input('اكتب Device ID كاملًا لتأكيد حذف التسجيل')
                    remove_confirm=st.checkbox('أؤكد حذف تسجيل هذا الجهاز القديم فقط مع حفظ تاريخه')
                    remove_submit=st.form_submit_button('حذف تسجيل الجهاز القديم',type='primary')
                if remove_submit:
                    if not remove_confirm:st.error('أكد حذف التسجيل أولًا')
                    else:
                        result=action_request(chosen,'unregister',remove_id.strip())
                        st.session_state['_device_registry_notice']=result['message'];st.rerun()
            elif device.get('registration_state')=='unregistered':
                st.info('تسجيل الجهاز محذوف؛ السجل المعروض للمراجعة فقط. أضف نفس المعرّف من إضافة جهاز جديد ثم اعتمده من الجهاز نفسه.')
            targets={int(b['id']):str(b['branch_name']) for b in branches if b.get('is_active',1)}
            if targets and device['is_active'] and _validated_role() in ('Super_Admin','Manager'):
                with st.form('device_admin_edit_'+chosen,clear_on_submit=False):
                    name=st.text_input('اسم الجهاز',value=device.get('device_name') or ('جهاز '+str(device['device_number'])),max_chars=80)
                    bid=st.selectbox('الفرع المرتبط',list(targets),index=list(targets).index(int(device['branch_id'])) if int(device['branch_id']) in targets else 0,format_func=lambda value:targets[value])
                    number=st.number_input('رقم الجهاز داخل الفرع',min_value=1,max_value=999999999,value=int(device['device_number']),step=1)
                    approved=st.checkbox('أؤكد حفظ طلب التعديل لهذه الهوية؛ يُطبق من الجهاز نفسه بعد تأمين عملياته')
                    submitted=st.form_submit_button('حفظ طلب تعديل الجهاز')
                if submitted:
                    if not approved:st.error('يلزم تأكيد الهوية وطلب التعديل')
                    else:
                        result=save(chosen,bid,number,name.strip());st.session_state['_device_registry_notice']=result['message'];st.rerun()
            else:st.info('لا يُعاد تفعيل جهاز غير نشط أو تغيير هويته من هذه الشاشة تلقائيًا')

            if device['is_active'] and _validated_role() in ('Super_Admin','Manager'):
                st.subheader('إلغاء التسجيل أو إعادة التهيئة')
                st.info('إلغاء التسجيل يتيح الرقم لبديل بعد تأمين عمليات الجهاز ووصول إيصال التطبيق. الجهاز غير المتصل يبقى بانتظار الاتصال واعتماد Super Admin من تجهيز الجهاز. إعادة التهيئة تعيد تنزيل بيانات الفرع لنفس الهوية والرقم، مع حفظ السجل السابق.')
                for action,title in [('retire','إلغاء تسجيل الجهاز'),('reinitialize','إعادة تهيئة الجهاز')]:
                    with st.form('device_lifecycle_'+action+'_'+chosen):
                        st.markdown('**'+title+'**')
                        confirmation=st.text_input('اكتب Device ID كاملًا لتأكيد '+title)
                        confirmed_action=st.checkbox('أؤكد اختيار هذه الهوية؛ لا تُحذف الفواتير التاريخية')
                        submitted_action=st.form_submit_button(title)
                    if submitted_action:
                        if not confirmed_action:st.error('يلزم التأكيد قبل حفظ الطلب')
                        else:
                            result=action_request(chosen,action,confirmation.strip())
                            st.session_state['_device_registry_notice']='حُفظ طلب '+title+'؛ يظل الرقم محجوزًا حتى تأمين معاملات الجهاز ووصول إيصال التطبيق. لم تُحذف بياناته';st.rerun()

        if scoped:
            active=list(scoped)
            if active:
                st.subheader('استبدال الجهاز أو إعادة تسجيله بعد الصيانة')
                st.caption('Device ID هو هوية برمجية محفوظة محليًا، وليس رقم الهارد. إذا بقيت ملفات العمل، استخدم نفس الهوية وإعادة التهيئة. بعد تغيير الهارد أو Windows تظهر هوية جديدة: أدخلها هنا لتفويضها مع حفظ السجل السابق. عند غياب إثبات تأمين بيانات الجهاز القديم يبقى الطلب معلقًا.')
                with st.form('device_replacement_request'):
                    purpose=st.radio('نوع التفويض',['استبدال جهاز بجهاز آخر','إعادة التسجيل بعد صيانة الكمبيوتر أو تغيير الهارد / Windows'])
                    old_id=st.selectbox('الجهاز السابق',[d['device_id'] for d in active],format_func=lambda value:next(str(d['device_number'])+' — '+d['device_id'] for d in active if d['device_id']==value))
                    new_id=st.text_input('Device ID للجهاز البديل كما يظهر في تجهيز Windows',max_chars=36)
                    old_confirm=st.text_input('اكتب Device ID للجهاز السابق كاملًا لتأكيد الاستبدال')
                    immediate=st.checkbox('استكمال التشغيل فور تأمين المعلقات، من آخر حالة مؤكدة على السيرفر، دون تصفير أو إعادة ترقيم')
                    approved_replace=st.checkbox('أؤكد الاستبدال مع حفظ الهوية السابقة وسجل الفواتير')
                    replace=st.form_submit_button('حفظ طلب استبدال الجهاز')
                if replace:
                    if not approved_replace:st.error('يلزم تأكيد الاستبدال')
                    else:
                        if os.name=='nt':
                            from branch_auth import admin_request_device_replacement
                            result=admin_request_device_replacement(old_id,new_id.strip(),old_confirm.strip(),immediate=immediate)
                        else:
                            from views.device_lifecycle import request_replacement
                            result=request_replacement(conn,actor,old_id,new_id.strip(),old_confirm.strip(),immediate=immediate);conn.commit()
                        st.session_state['_device_registry_notice']=result.get('message') or ('الاستبدال متوقف حتى تأمين العمليات ووصول إيصال الجهاز السابق؛ لم يُلغَ اعتماده بعد.' if result.get('status')=='waiting_for_safe_retirement' else 'تم تأمين الجهاز السابق. اعتمد البديل ليبدأ من آخر حالة مركزية مؤكدة دون تصفير أو نقل فواتير.')
                        st.session_state['_device_registry_notice_level']='warning' if result.get('status')=='waiting_for_safe_retirement' else 'success'
                        st.rerun()
        replacements=[row for row in registry.get('replacements',[]) if int(row['branch_id'])==branch]
        if replacements:
            st.subheader('طلبات استبدال الأجهزة')
            st.dataframe([{'الطلب':row['command_id'],'الجهاز السابق':row['old_device_id'],'الجهاز البديل':row['new_device_id'],'الرقم':row['device_number'],'الحالة':('تم الاستبدال' if row['status']=='completed' else 'جاهز لاعتماد البديل' if row.get('safety_confirmed') else 'بانتظار تأمين الجهاز السابق'),'متابعة مالية':'معلقات السابق محفوظة للتسوية؛ لم تُعتبر متزامنة' if row.get('financial_review_required') else 'وفق إيصال التأمين'} for row in replacements],hide_index=True,width='stretch')
        branch_changes=[r for r in changes if int(r['from_branch_id'])==branch or int(r['to_branch_id'])==branch]
        if branch_changes:
            st.subheader('طلبات تعديل تسجيل الأجهزة')
            st.dataframe([{'معرّف الطلب':r['command_id'],'معرّف الجهاز':r['device_id'],'الفرع المطلوب':labels.get(int(r['to_branch_id']),r['to_branch_id']),'الرقم المطلوب':r['to_device_number'],'الاسم المطلوب':r['device_name'],'الحالة':states.get(r['status'],r['status']),'السبب':r.get('error') or ''} for r in branch_changes],hide_index=True,use_container_width=True)
            cancellable=[r['command_id'] for r in branch_changes if r['status']=='pending']
            if cancellable:
                command=st.selectbox('طلب لم يُطبق ويمكن إلغاؤه',cancellable,key='device_admin_cancel_id')
                if st.button('إلغاء طلب التعديل المحدد'):
                    cancel(command);st.session_state['_device_registry_notice']='تم إلغاء الطلب؛ لم تتغير هوية الجهاز أو بياناته';st.rerun()
        actions=[a for a in registry.get('actions',[]) if int(a['branch_id'])==branch]
        if actions:
            st.subheader('حالة إلغاء التسجيل وإعادة التهيئة')
            st.dataframe([{'معرّف الطلب':a['command_id'],'الجهاز':a['device_id'],'الرقم':a['device_number'],'الإجراء':'إعادة التهيئة' if a['action']=='reinitialize' else 'إلغاء التسجيل','الحالة':{'applied':'تم التطبيق','cancelled_unregistered':'أُلغي بعد حذف التسجيل'}.get(a['status'],'بانتظار اتصال الجهاز واعتماد الإدارة'),'السبب':a.get('error') or ''} for a in actions],hide_index=True,use_container_width=True)
        st.info('اعتماد البديل يتوقف عند تعذر تأمين المعلقات. بعد إيصال التأمين، يستكمل من آخر بيانات مؤكدة. إذا كان القرص القديم مفقودًا فلا يمكن استرجاع بيانات لم تصل للسيرفر من العدم. لتطبيق طلب محفوظ: يسجل Super Admin الدخول أونلاين من «تجهيز الجهاز» على الجهاز المقصود، ويؤكد الطلب. يبقى الطلب معلقًا حتى وصول إيصال التطبيق من الجهاز.')
    except Exception as error:
        if conn is not None:conn.rollback()
        from views.device_registry import device_error_message
        show_operation_error(error, announce=True, context='views/branch_devices.py:174')
    finally:
        if conn is not None:conn.close()


def render_device_invoices(device,actor,conn=None):
    st.subheader('الفواتير الحقيقية المؤكدة لهذا الجهاز')
    st.caption('قراءة الفواتير المحفوظة على السيرفر فقط؛ لا تشمل فواتير لم تصل بعد، ولا تُعد البيانات لحظية عند انقطاع الجهاز.')
    page=int(st.number_input('صفحة الفواتير — 50 سجلًا',min_value=1,max_value=100000,value=1,key='device_invoice_page_'+device['device_id']))
    st.button('تحديث الفواتير',key='device_invoice_refresh_'+device['device_id'])
    if os.name=='nt':
        from branch_auth import admin_device_invoices
        data=admin_device_invoices(device['device_id'],device['branch_id'],page)
    else:
        from views.device_registry import device_invoice_page
        data=device_invoice_page(conn,actor,device['device_id'],device['branch_id'],page)
    rows=data['invoices']
    if not rows:st.info('لا توجد فواتير مالية محفوظة في هذه الصفحة');return
    st.dataframe([{'رقم الفاتورة الأصلي':r.get('invoice_number') or 'غير محفوظ','تاريخ ووقت الإصدار':r.get('sold_at'),
        'القيمة':r.get('total_amount'),'الوردية المسجلة':r.get('shift_status'),'معرّف الوردية':r.get('shift_uuid') or 'غير محفوظ',
        'الكاشير':r.get('user_id'),'حالة المزامنة':r['sync_status'],'وقت إيصال الرفع':r.get('received_at') or 'غير متوفر'} for r in rows],hide_index=True,use_container_width=True)
    selected=st.selectbox('تفاصيل الفاتورة',[r['id'] for r in rows],format_func=lambda value:next(str(r.get('invoice_number') or r['id']) for r in rows if r['id']==value),key='device_invoice_detail_'+device['device_id'])
    invoice=next(r for r in rows if r['id']==selected)
    if invoice['items']:
        st.dataframe([{'الصنف':i.get('name') or i.get('item_name') or i.get('id'),'الكمية':i.get('qty',i.get('quantity')),'السعر':i.get('price'),'الإجمالي المحفوظ':i.get('total')} for i in invoice['items']],hide_index=True,use_container_width=True)
    else:st.info('لا توجد تفاصيل أصناف محفوظة يمكن عرضها لهذه الفاتورة؛ لم تُستنتج بيانات بديلة.')


def render_branch_devices(branch_id):
    from views.dashboard import _validated_role
    if _validated_role() not in ('Super_Admin','Admin','Manager'):return
    if os.name=='nt':
        from branch_auth import admin_device_registry
        registry=admin_device_registry()
    else:
        from database import get_db_connection
        from views.device_registry import list_registered
        c=get_db_connection()
        try:registry=list_registered(c,st.session_state.get('user_id'))
        finally:c.close()
    from views.update_distribution import render_release_summary,device_status_rows
    st.subheader('أجهزة الفرع والتحديثات')
    render_release_summary(registry)
    devices=[d for d in registry.get('devices',[]) if int(d['branch_id'])==int(branch_id) and d.get('registration_state')!='unregistered']
    if devices:st.dataframe(device_status_rows(devices),hide_index=True,use_container_width=True)
    else:st.info('لا توجد أجهزة مسجلة لهذا الفرع')
    if st.button('فتح أجهزة هذا الفرع وفواتيرها',key='open_branch_devices_'+str(branch_id)):
        current=st.session_state.get('page','🏢 إدارة الفروع')
        history=list(st.session_state.get('_nav_history',[]))
        if not history or history[-1]!=current:history.append(current)
        st.session_state['_nav_history']=history[-30:]
        st.session_state['_device_branch_request']=int(branch_id)
        st.session_state['page']='__BRANCH_DEVICE_ADMIN__'
        st.rerun()
