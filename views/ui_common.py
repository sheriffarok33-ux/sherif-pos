import streamlit as st
from database import get_db_connection


def back_button(key="global_back_btn"):
    """Shared back navigation: never log out, clear a basket or reset form fields."""
    if st.session_state.get('_back_rendered_this_run'):return
    st.session_state['_back_rendered_this_run']=True
    current=st.session_state.get('page','🏠 الرئيسية واللوحة')
    def go_back():
        history=list(st.session_state.get('_nav_history',[]))
        allowed=st.session_state.get('_nav_allowed_targets')
        target=None
        while history:
            entry=history.pop()
            value=entry.get('page') if isinstance(entry,dict) else entry
            if value!=current and (allowed is None or value in allowed):
                target=value
                if isinstance(entry,dict):
                    for name,value in entry.get('state',{}).items():
                        if name in st.session_state.get('_nav_context_keys',[]) and isinstance(value,str):st.session_state[name]=value
                break
        if target is None:
            target='🛒 نقطة البيع (POS)' if st.session_state.get('role')=='Cashier' else '🏠 الرئيسية واللوحة'
        # Detach registered widget state before Streamlit cleans hidden widgets.
        for name in st.session_state.get('_entry_fields',{}):
            if name in st.session_state:st.session_state[name]=st.session_state[name]
        st.session_state['_nav_history']=history
        st.session_state['page']=target
    c_back,_=st.columns([1.15,8.85])
    with c_back:
        st.button('⬅️ رجوع',key=key,use_container_width=True,on_click=go_back)
    # Unsubmitted st.form edits do not exist on Python yet. Block navigation
    # rather than silently dropping them. No value is sent to a separate store.
    import streamlit.components.v1 as components
    components.html("""<script>
    const d=window.parent.document;
    if(!d.__azBackGuard){
      const dirty=new Set();
      d.__azBackGuard=true;
      d.addEventListener('input',e=>{const f=e.target.closest('[data-testid="stForm"]');if(f)dirty.add(f);},true);
      d.addEventListener('change',e=>{const f=e.target.closest('[data-testid="stForm"]');if(f)dirty.add(f);},true);
      d.addEventListener('click',e=>{
        const b=e.target.closest('button');if(!b)return;
        for(const f of Array.from(dirty))if(!f.isConnected)dirty.delete(f);
        if(b.closest('[data-testid="stFormSubmitButton"]')){const f=b.closest('[data-testid="stForm"]');if(f)dirty.delete(f);return;}
        if(b.innerText.trim()==='⬅️ رجوع' && dirty.size){
          e.preventDefault();e.stopImmediatePropagation();
          window.parent.alert('توجد تعديلات داخل نموذج لم تُرسل بعد. احفظ النموذج أولًا حتى لا تفقدها عند الرجوع.');
        }
      },true);
    }
    </script>""",height=0)


def item_alerts(branch_id=None, key="item_alerts"):
    """تنبيهات مضغوطة: Dropdown فقط، والتفاصيل لا تظهر إلا عند طلب المستخدم."""
    role = str(st.session_state.get("role", "")).strip().lower()
    manager = role in {
        "super_admin", "admin", "manager", "supervisor", "general_supervisor", "branch_supervisor",
        "مدير", "المدير", "مشرف عام", "مشرف فرع"
    }
    from offline_store import local_display_scope
    scope=local_display_scope(st.session_state.get('role',''),branch_id)
    if scope is not None:branch_id=scope[0]
    conn = get_db_connection()
    try:
        import sqlite3
        raw=getattr(conn,'_conn',conn)
        limit_sql="date('now','localtime','+30 day')" if isinstance(raw,sqlite3.Connection) else "CURRENT_DATE + INTERVAL '30 days'"
        params = []
        branch_clause = ""
        if branch_id:
            branch_clause = " AND i.branch_id=?"
            params.append(branch_id)

        expiry = conn.execute(f"""
            SELECT i.item_name, i.quantity, b.branch_name,
                   ib.expiry_date, ib.remaining_quantity
            FROM inventory_batches ib
            JOIN items i ON i.id=ib.item_id
            LEFT JOIN branches b ON b.id=i.branch_id
            WHERE COALESCE(ib.remaining_quantity,0)>0
              AND ib.expiry_date IS NOT NULL
              AND date(ib.expiry_date) <= {limit_sql}
              {branch_clause}
            ORDER BY date(ib.expiry_date), i.item_name
            LIMIT 30
        """, params).fetchall()

        low = []
        if manager:
            low = conn.execute(f"""
                SELECT i.item_name, i.quantity, b.branch_name
                FROM items i
                LEFT JOIN branches b ON b.id=i.branch_id
                WHERE COALESCE(i.quantity,0)<=5 {branch_clause}
                ORDER BY i.quantity, i.item_name
                LIMIT 30
            """, params).fetchall()

        total = len(expiry) + len(low)
        if not total:
            return

        choice = st.selectbox(
            f"🚨 التنبيهات ({total})",
            ["إخفاء التفاصيل", "عرض تنبيهات الصلاحية"] +
            (["عرض تنبيهات المخزون المنخفض"] if low else []) +
            (["عرض كل التنبيهات"] if low and expiry else []),
            key=f"{key}_dropdown",
            label_visibility="visible",
        )

        show_expiry = choice in ("عرض تنبيهات الصلاحية", "عرض كل التنبيهات")
        show_low = choice in ("عرض تنبيهات المخزون المنخفض", "عرض كل التنبيهات")

        if show_expiry and expiry:
            st.warning("⚠️ منتهي أو قريب الانتهاء")
            rows = [{
                "الصنف": r["item_name"],
                "الفرع/المخزن": r["branch_name"] or "-",
                "الصلاحية": str(r["expiry_date"]),
                "المتبقي": float(r["remaining_quantity"] or 0),
            } for r in expiry]
            st.dataframe(rows, hide_index=True, use_container_width=True)

        if show_low and low:
            st.warning("⚠️ رصيد 5 أو أقل")
            rows = [{
                "الصنف": r["item_name"],
                "الفرع/المخزن": r["branch_name"] or "-",
                "الرصيد": float(r["quantity"] or 0),
            } for r in low]
            st.dataframe(rows, hide_index=True, use_container_width=True)
    except Exception:
        __import__('logging').getLogger(__name__).exception('Inventory alerts unavailable')
        # التنبيه لا يجب أن يعطل شاشة البيع أو أي عملية أساسية.
        return
    finally:
        conn.close()


def apply_rtl():
    """Direction/alignment only: retain geometry, colors, fonts and controls."""
    st.markdown('<style>\nhtml,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stSidebar"]{direction:rtl}\n[data-testid="stMarkdownContainer"],[data-testid="stCaptionContainer"],label,h1,h2,h3,h4,h5,h6,p{ text-align:right;unicode-bidi:plaintext }\n[data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea{unicode-bidi:plaintext;text-align:right}\ninput[type="number"],input[type="password"],input[dir="ltr"],pre,code,kbd{direction:ltr;unicode-bidi:isolate}\npre,code,kbd,input[dir="ltr"]{text-align:left}\n</style>',unsafe_allow_html=True)
    script="<script>\nconst d=document;\nfunction alignInputs(){for(const input of d.querySelectorAll('input,textarea')){\n const type=(input.type||'').toLowerCase();if(['file','radio','checkbox','hidden','button','submit'].includes(type))continue;\n const label=input.getAttribute('aria-label')||'';\n if(type==='password' && /الرقم السري|رقم سري/.test(label))input.setAttribute('inputmode','numeric');\n const dir=['number','password','email','url'].includes(type)||/باركود|barcode|كود الصنف|رقم الفاتورة|invoice|معرّف|المعرّف|device id/i.test(label)?'ltr':'auto';\n if(input.getAttribute('dir')!==dir)input.setAttribute('dir',dir);\n}}\nalignInputs();if(!d.__abuzaidRTLObserver){d.__abuzaidRTLObserver=new MutationObserver(alignInputs);d.__abuzaidRTLObserver.observe(d.body,{childList:true,subtree:true});}\n</script>"
    try:st.html(script,unsafe_allow_javascript=True)
    except TypeError:
        import streamlit.components.v1 as components
        components.html(script.replace('const d=document;','const d=window.parent.document;'),height=0)
