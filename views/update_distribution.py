"""Super Admin distribution controls for the existing signed updater."""
import os
from pathlib import Path
import streamlit as st
from views.technical_visibility import technical_details_allowed, require_technical_reader


def render_distribution():
    from views.dashboard import _validated_role
    role=_validated_role()
    if role=='Admin':
        render_installation_dashboard();return
    if role!='Super_Admin':return
    with st.container(border=True):
        st.subheader('تحديثات البرنامج وأجهزة الفروع')
        try:
            if os.name=='nt':
                from branch_auth import admin_update_distribution,admin_set_update_distribution
                data=admin_update_distribution();save=admin_set_update_distribution
            else:
                from database import get_db_connection
                from views.device_registry import super_admin
                from server_update_service import create_update_router,set_distribution_scope
                actor=st.session_state.get('user_id');root=Path(__file__).resolve().parents[1]/'update_releases'
                def devices():
                    c=get_db_connection()
                    try:return [dict(r) for r in c.execute('SELECT d.device_id,d.branch_id,d.device_number,b.branch_name FROM branch_devices d JOIN branches b ON b.id=d.branch_id WHERE d.is_active ORDER BY d.branch_id,d.device_number').fetchall()]
                    finally:c.close()
                c=get_db_connection()
                try:super_admin(c,actor)
                finally:c.close()
                router=create_update_router(root,lambda:None,lambda:None,devices)
                data=next(route.endpoint for route in router.routes if route.path=='/admin/updates')({'id':actor})
                def save(sequence,mode,bid):
                    c=get_db_connection()
                    try:super_admin(c,actor)
                    finally:c.close()
                    return set_distribution_scope(root,sequence,mode,bid,actor)
            sequence=int(data.get('release_seq') or 0)
            render_release_summary(data)
            branches={int(d['branch_id']):d.get('branch_name') or str(d['branch_id']) for d in data.get('devices',[])}
            with st.form('signed_update_scope'):
                mode=st.selectbox('نطاق التحديث',['all','branch'],index=1 if data.get('scope',{}).get('mode')=='branch' else 0,format_func=lambda value:'جميع الفروع والأجهزة المسجلة' if value=='all' else 'فرع محدد بجميع أجهزته')
                ids=list(branches)
                selected=data.get('scope',{}).get('branch_id')
                bid=st.selectbox('فرع التوزيع',ids,index=ids.index(selected) if selected in ids else 0,format_func=lambda value:branches[value]) if ids else None
                confirmed=st.checkbox('أؤكد نطاق التوزيع؛ الأجهزة خارجه لن تتمكن من تنزيل الحزمة')
                submit=st.form_submit_button('حفظ نطاق التحديث')
            if submit:
                if not confirmed:st.error('أكد نطاق التحديث أولًا')
                elif mode=='branch' and bid is None:st.error('لا يوجد فرع له أجهزة نشطة')
                else:save(sequence,mode,bid if mode=='branch' else None);st.success('حُفظ نطاق التوزيع');st.rerun()
            rows=data.get('devices',[])
            if rows:st.dataframe([{'الفرع':r.get('branch_name') or r['branch_id'],**row,'حالة التحديث':r.get('update_status','بانتظار التحديث')} for r,row in zip(rows,device_status_rows(rows))],hide_index=True,use_container_width=True)
            else:st.info('لا توجد أجهزة مسجلة للعرض')
        except Exception as exc:st.info('تعذر تحميل إدارة نطاق التحديث: '+str(exc))


def installation_time(value):
    if value is None:return 'غير محفوظ في الإيصالات القديمة'
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(float(value),ZoneInfo('Africa/Tripoli')).strftime('%Y-%m-%d %H:%M:%S')


def render_release_summary(data):
    info=data.get('software',data);server=info.get('server') or {}
    st.caption('السيرفر الجاري: '+str(server.get('version','غير متوفر'))+' — تحديث '+str((4 if server.get('release_seq') in (53,54,55,56) else server.get('update_number',server.get('release_seq','غير متوفر'))))+
        ' | تحديث Windows المنشور للتوزيع: '+str((4 if info.get('release_seq') in (53,54,55,56) else info.get('update_number',info.get('release_seq','غير متوفر')))))
    st.caption('المنشور ليس مثبتًا تلقائيًا؛ المثبت أدناه مستند إلى إيصال صحة وحماية بيانات. تاريخ أول تأكيد يُحفظ للإيصالات الجديدة فقط.')


def device_status_rows(devices):
    return [{'الفرع':d.get('branch_name') or str(d['branch_id']),
        'رقم الجهاز':d['device_number'],'Device ID':d['device_id'],
        'الحالة':'نشط' if d.get('is_active',True) else 'تاريخي غير نشط',
        'حالة الاتصال':d.get('connection_state','غير معروف'),
        'آخر اتصال موثّق':installation_time(d.get('last_device_activity_at')) if d.get('last_device_activity_at') is not None else str(d.get('last_seen_at') or 'غير متوفر'),
        'مصدر رصد الاتصال':d.get('activity_source') or 'غير متوفر',
        'الإصدار المثبت فعليًا':d.get('installed_version') or 'غير مؤكد',
        'التحديث المثبت المؤكد':(4 if d.get('installed_release_seq') in (53,54,55,56) else d.get('installed_update_number',d.get('installed_release_seq'))) if d.get('installed_release_seq') is not None else 'غير مؤكد',
        'الترقيم':'الجديد' if d.get('row_numbering_epoch')==2 else 'القديم',
        'آخر تحديث معتمد':(4 if d.get('latest_available_release_seq') in (53,54,55,56) else d.get('latest_update_number','غير مؤكد')),
        'وقت تأكيد التثبيت':installation_time(d.get('installation_confirmed_at')),
        'حالة التحديث':d.get('update_state','ينتظر التحديث'),
        'سبب انتظار التثبيت':d.get('update_wait_reason') or '',
        'سبب الفشل':d.get('update_failure_reason') or '',
        'تفاصيل الحالة':{'ready_after_exit':'الحزمة جاهزة وبانتظار الإغلاق الآمن','deferred_until_safe':'بانتظار الوضع الآمن للتثبيت','downloading':'جارٍ التنزيل','current':'آخر فحص للجهاز'}.get(d.get('update_detail'),d.get('update_detail') or ''),
        'آخر تسلسل مُبلّغ':d.get('reported_release_seq') if d.get('reported_release_seq') is not None else 'لم يبلّغ',
        'آخر بلاغ تحديث':installation_time(d.get('last_update_report_at')) if d.get('last_update_report_at') else 'لم يبلّغ'} for d in devices]


def render_installation_dashboard():
    from views.dashboard import _validated_role
    if not technical_details_allowed():return
    with st.container(border=True):
        st.subheader('حالة تثبيت التحديثات على أجهزة الفروع')
        if st.button('تحديث حالة الأجهزة',key='fleet_installation_refresh'):st.rerun()
        try:
            if os.name=='nt':
                from branch_auth import admin_update_distribution
                data=admin_update_distribution()
            else:
                from database import get_db_connection
                from server_update_service import installation_view
                from views.device_registry import super_admin
                c=get_db_connection()
                try:
                    require_technical_reader(c,st.session_state.get('user_id'),st.session_state.get('role'))
                    heartbeat=c.execute("SELECT to_regclass('branch_device_heartbeats') AS tbl").fetchone()['tbl']
                    extra=',h.last_seen_at,EXTRACT(EPOCH FROM (LOCALTIMESTAMP-h.last_seen_at)) AS heartbeat_age_seconds' if heartbeat else ',NULL AS last_seen_at,NULL AS heartbeat_age_seconds'
                    join=' LEFT JOIN branch_device_heartbeats h ON h.device_id=d.device_id AND h.branch_id=d.branch_id' if heartbeat else ''
                    rows=[dict(x) for x in c.execute('SELECT d.device_id,d.branch_id,d.device_number,d.is_active,b.branch_name'+extra+' FROM branch_devices d JOIN branches b ON b.id=d.branch_id'+join+' ORDER BY d.branch_id,d.device_number').fetchall()]
                finally:c.close()
                data=installation_view(Path(__file__).resolve().parents[1]/'update_releases',rows)
            render_release_summary(data)
            rows=data.get('devices',[])
            cols=st.columns(5)
            for col,label in zip(cols,('محدّث','ينتظر التحديث','فشل التحديث','متصل','غير متصل')):
                count=sum(d.get('connection_confirmed')==(label=='متصل') for d in rows) if label in ('متصل','غير متصل') else sum(d.get('update_state')==label for d in rows)
                col.metric(label,count)
            if rows:st.dataframe(device_status_rows(rows),hide_index=True,use_container_width=True)
            else:st.info('لا توجد أجهزة مسجلة')
        except Exception:
            st.warning('حالة التحديث غير متاحة.')
