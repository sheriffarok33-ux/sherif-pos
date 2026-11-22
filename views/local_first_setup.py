"""First local setup: no automatic changes to an existing installation."""
import streamlit as st
from offline_store import get_local_connection, _schedule_invoice_journal
from sherif_local_identity import provision_fresh


def show_local_first_setup():
    st.title('إعداد SHERIF لأول مرة')
    st.caption('أنشئ بيانات المنشأة والفرع والجهاز وحساب المدير على هذا الجهاز.')
    with st.form('sherif_local_first_setup'):
        company=st.text_input('اسم المنشأة')
        activity=st.text_input('نوع النشاط')
        branch=st.text_input('اسم الفرع')
        device=st.text_input('اسم الجهاز')
        username='admin'
        st.caption('اسم المدير: admin')
        password=st.text_input('الرقم السري للمدير (4 أرقام)',type='password',max_chars=4)
        confirm=st.text_input('تأكيد الرقم السري',type='password',max_chars=4)
        submit=st.form_submit_button('حفظ وبدء الاستخدام')
    if not submit:return
    if password!=confirm:
        st.error('كلمتا المرور غير متطابقتين.')
        return
    import os
    import offline_store
    named = bool(os.environ.get('SHERIF_DATA_DIR'))
    if named:
        from sherif_paths import reserve_company_db, bind_company_db
        previous=offline_store.LOCAL_DB
        target=reserve_company_db(company)
        offline_store.LOCAL_DB=target
        offline_store._LOCAL_CONNECTION_SCHEMA_READY=False
    conn=get_local_connection(queue_writes=False)
    try:
        provision_fresh(getattr(conn,'_conn',conn),company,branch,device,username,password,activity)
        if named:
            bind_company_db(target)
            import backup_manager
            backup_manager.LOCAL_DB=target
        _schedule_invoice_journal()
    except (ValueError,RuntimeError) as exc:
        if named:
            offline_store.LOCAL_DB=previous
            offline_store._LOCAL_CONNECTION_SCHEMA_READY=False
        st.error(str(exc))
        return
    finally:
        conn.close()
    st.cache_data.clear()
    st.success('تم إعداد الجهاز محليًا. سجل الدخول بحساب المدير.')
    st.rerun()
