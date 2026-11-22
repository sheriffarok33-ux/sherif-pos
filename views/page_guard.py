"""Page-level recovery UI. Log real errors; never roll back unrelated transactions."""
import importlib
import logging
import re
import sys
import threading
import uuid
from pathlib import Path

_LOG=logging.getLogger(__name__)
_RELOAD_LOCK=threading.RLock()

def _current_callback(callback):
    """Refresh only a newly deployed view, before invoking its page function."""
    name=getattr(callback,'__module__','')
    module=sys.modules.get(name)
    if not name.startswith('views.') or module is None:return callback
    def refresh(target):
        path=getattr(target,'__file__',None)
        if not path:return target
        header=Path(path).read_text(encoding='utf-8-sig')[:8192]
        found=re.search(r'^_PAGE_ERROR_UI_REVISION = (\d+)$',header,re.M)
        if found and getattr(target,'_PAGE_ERROR_UI_REVISION',None)!=int(found.group(1)):
            importlib.invalidate_caches()
            return importlib.reload(target)
        return target
    with _RELOAD_LOCK:
        # Purchases imported its schema helper by value. Refresh the provider first.
        if name=='views.purchases':
            documents=sys.modules.get('views.documents')
            if documents is not None:refresh(documents)
        current=refresh(module)
        return getattr(current,getattr(callback,'__name__',''),callback)

def _guidance(error):
    code=str(getattr(error,'pgcode','') or '')
    sqlite_name=str(getattr(error,'sqlite_errorname','') or '')
    if code=='42501' or isinstance(error,PermissionError):
        return 'تعذر تنفيذ الطلب بالصلاحيات الحالية. تواصل مع الإدارة برقم المتابعة.'
    if code in ('42P01','42703'):
        return 'هذه الشاشة تحتاج تحديثًا إداريًا. ارجع للرئيسية وأرسل رقم المتابعة للإدارة.'
    if code.startswith('08') or isinstance(error,ConnectionError):
        return 'تعذر الاتصال بخدمة البيانات. تحقق من الاتصال ثم اضغط «إعادة المحاولة».'
    if sqlite_name in ('SQLITE_BUSY','SQLITE_LOCKED'):
        return 'البيانات قيد الاستخدام حاليًا. انتظر انتهاء العملية الجارية ثم اضغط «إعادة المحاولة».'
    if code=='25P02':
        return 'تعذر إكمال قراءة البيانات. اضغط «إعادة المحاولة» لفتح اتصال جديد، وإذا تكرر العطل أبلغ الإدارة.'
    return 'تعذر استكمال عرض الشاشة. يمكنك إعادة المحاولة أو الرجوع للرئيسية؛ أبلغ الإدارة إذا تكرر العطل.'

def show_operation_error(error,announce=True,context=''):
    import streamlit as st
    page=str(st.session_state.get('page',''))
    fingerprint=page+'|'+context+'|'+type(error).__name__+'|'+str(getattr(error,'pgcode','') or '')
    refs=st.session_state.setdefault('_screen_error_refs',{})
    incident=refs.get(fingerprint)
    if not incident:
        incident=uuid.uuid4().hex[:10].upper()
        if len(refs)>=16:refs.pop(next(iter(refs)))
        refs[fingerprint]=incident
    _LOG.error('Application page error incident=%s page=%s context=%s',incident,page,context,
               exc_info=(type(error),error,error.__traceback__))
    st.session_state['_last_screen_failure']={'incident':incident,'error_type':type(error).__name__}
    if announce:st.error('تعذر استكمال العملية الحالية.')
    st.info(_guidance(error))
    st.caption('رقم المتابعة للإدارة: '+incident)
    st.caption('احتفظ بالعملية المفتوحة. لا تعِد اعتماد فاتورة سابقة قبل التأكد من الأرشيف.')
    def retry():
        st.session_state.pop('_last_screen_failure',None)
        st.session_state.get('_screen_error_refs',{}).pop(fingerprint,None)
    def home():
        retry()
        st.session_state['page']='🛒 نقطة البيع (POS)' if st.session_state.get('role')=='Cashier' else '🏠 الرئيسية واللوحة'
    from streamlit.elements.lib.form_utils import is_in_form
    if is_in_form(st._main):
        st.caption('للخروج من التعثر استخدم القائمة الجانبية، ثم افتح الشاشة مجددًا. لا تعتمد عملية مالية مرتين.')
        return incident
    left,right=st.columns(2)
    left.button('إعادة المحاولة',key='page_retry_'+incident,on_click=retry)
    right.button('العودة للرئيسية',key='page_home_'+incident,on_click=home)
    return incident


def guarded_page_call(callback,*args,**kwargs):
    try:
        return _current_callback(callback)(*args,**kwargs)
    except Exception as error:
        # Streamlit Stop/Rerun and process-control exceptions inherit BaseException.
        # Financial handlers retain ownership of rollback/commit and pending carts.
        show_operation_error(error,context=getattr(callback,'__module__','')+'.'+getattr(callback,'__name__','page'))
        return None

