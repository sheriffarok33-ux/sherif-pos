"""Read-only central inventory view; never merges remote rows into POS stock."""
from views.test_branch_policy import report_branch_ids
import json
import math
import os
import html
from datetime import datetime, timezone


GLOBAL_ROLES = ('Super_Admin','Admin','Manager','General_Supervisor')

def validate_snapshot(data, role):
    if not isinstance(data, dict) or data.get('read_only') is not True:
        raise ValueError('Invalid read-only snapshot')
    if (data.get('scope') not in ('all_branches','branch') or (data.get('scope') == 'all_branches' and role not in GLOBAL_ROLES)):
        raise ValueError('Global data permission not confirmed')
    if not isinstance(data.get('branches'), list) or not isinstance(data.get('items'), list):
        raise ValueError('Incomplete central inventory snapshot')
    branches = []
    ids = set()
    for row in data['branches']:
        bid = row['id']
        if type(bid) is not int or bid <= 0 or bid in ids:
            raise ValueError('Invalid branch identity')
        ids.add(bid)
        branches.append({k: row.get(k) for k in ('id', 'branch_name', 'branch_type', 'is_active')})
    items = []
    item_ids = set()
    for row in data['items']:
        if (type(row['id']) is not int or row['id'] <= 0 or row['id'] in item_ids
                or type(row['branch_id']) is not int or row['branch_id'] not in ids):
            raise ValueError('Invalid central item identity or scope')
        item_ids.add(row['id'])
        item = {k: row.get(k) for k in ('id', 'branch_id', 'item_name', 'item_code', 'unit')}
        for key in ('quantity', 'avg_cost', 'buy_price', 'sale_price'):
            value = row.get(key)
            if isinstance(value, bool):
                raise ValueError('Invalid stock value')
            value = float(value or 0)
            if not math.isfinite(value):
                raise ValueError('Invalid stock value')
            item[key] = value
        items.append(item)
    result = {'read_only': True, 'scope': data['scope'], 'user_id':data.get('user_id'), 'branches': branches, 'items': items}
    if 'metrics' in data:
        if not isinstance(data['metrics'],list):
            raise ValueError('Invalid branch financial snapshot')
        metrics=[]
        seen=set()
        for row in data['metrics']:
            bid=row.get('branch_id')
            if type(bid) is not int or bid not in ids or bid in seen:
                raise ValueError('Invalid financial branch scope')
            seen.add(bid)
            metric={'branch_id':bid}
            count=row.get('invoice_count')
            if type(count) is not int or count < 0:
                raise ValueError('Invalid invoice count')
            metric['invoice_count']=count
            for key in ('sales','expenses','revenues','purchases'):
                value=row.get(key)
                if isinstance(value,bool) or value is None or not math.isfinite(float(value)):
                    raise ValueError('Invalid financial total')
                metric[key]=float(value)
            metrics.append(metric)
        if seen != ids:
            raise ValueError('Incomplete financial snapshot')
        result['metrics']=metrics
    alerts=data.get('alerts',[])
    if not isinstance(alerts,list) or any(r.get('branch_id') not in ids or r.get('type') not in ('expired','expiry_7','expiry_30','low_stock') for r in alerts):
        raise ValueError('Invalid alert scope')
    result['alerts']=alerts
    records=data.get('records',{})
    if not isinstance(records,dict):raise ValueError('Invalid record snapshot')
    for name in ('invoices','expenses'):
        if not isinstance(records.get(name,[]),list) or any(r.get('branch_id') not in ids for r in records.get(name,[])):
            raise ValueError('Invalid record scope')
    result['records']=records
    result['invoice_receipts_supported']='last_synced_invoices' in data
    receipts=data.get('last_synced_invoices',[])
    if not isinstance(receipts,list):raise ValueError('Invalid invoice receipt summary')
    seen_receipts=set()
    for receipt in receipts:
        if not isinstance(receipt,dict) or type(receipt.get('branch_id')) is not int or receipt['branch_id'] not in ids or receipt['branch_id'] in seen_receipts:
            raise ValueError('Invoice receipt outside authorized branch scope')
        if not receipt.get('offline_uuid') or type(receipt.get('remote_invoice_id')) is not int or receipt['remote_invoice_id']<=0 or not isinstance(receipt.get('received_at'),str):
            raise ValueError('Unconfirmed invoice receipt summary')
        datetime.fromisoformat(receipt['received_at'].replace('Z','+00:00'))
        seen_receipts.add(receipt['branch_id'])
    result['last_synced_invoices']=receipts
    return result


def build_alerts(items, batches, today):
    from datetime import date
    today=date.fromisoformat(str(today)[:10])
    by_id={r['id']:r for r in items}
    alerts=[]
    batch_quantities={}
    covered={b['item_id'] for b in batches}
    batches=list(batches)+[{'item_id':r['id'],'branch_id':r['branch_id'],'remaining_quantity':r.get('quantity',0),'expiry_date':r.get('expiry_date')} for r in items if r['id'] not in covered and r.get('expiry_date')]
    for batch in batches:
        item=by_id.get(batch['item_id'])
        if not item or item['branch_id']!=batch['branch_id']:continue
        qty=float(batch.get('remaining_quantity') or 0)
        batch_quantities[item['id']]=batch_quantities.get(item['id'],0)+qty
        if qty<=0 or item.get('no_expiry') or not batch.get('expiry_date'):continue
        try:days=(date.fromisoformat(str(batch['expiry_date'])[:10])-today).days
        except (ValueError,TypeError):continue
        if days>30:continue
        alerts.append({'branch_id':item['branch_id'],'item_id':item['id'],'item_code':item.get('item_code'),'item_name':item.get('item_name'),'quantity':qty,'expiry_date':str(batch['expiry_date'])[:10],'days_left':days,'type':'expired' if days<0 else ('expiry_7' if days<=7 else 'expiry_30')})
    for item in items:
        qty=batch_quantities.get(item['id'],float(item.get('quantity') or 0))
        threshold=max(0,float(item.get('low_stock_limit',5)))
        if qty<=threshold:
            alerts.append({'branch_id':item['branch_id'],'item_id':item['id'],'item_code':item.get('item_code'),'item_name':item.get('item_name'),'quantity':qty,'threshold':threshold,'type':'low_stock'})
    return alerts


def load_overview(user_id, role, force=False, branch_id=None):
    if type(user_id) is not int or user_id<=0:raise PermissionError('Account required')
    if os.name!='nt':
        from server_api import dashboard_snapshot
        data=validate_snapshot(dashboard_snapshot(user_id),role)
        return data,datetime.now(timezone.utc).isoformat(timespec='seconds'),'online'
    from offline_store import get_local_connection, _request_with_auth_retry
    conn=get_local_connection(queue_writes=False)
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS central_inventory_view_cache (user_id INTEGER PRIMARY KEY,payload TEXT NOT NULL,fetched_at TEXT NOT NULL)')
        row=conn.execute('SELECT payload,fetched_at FROM central_inventory_view_cache WHERE user_id=?',(user_id,)).fetchone()
        conn.commit();cached=None
        if row:
            try:
                cached=validate_snapshot(json.loads(row[0]),role)
                if cached.get('user_id') not in (None,user_id):raise ValueError('Account mismatch')
                if role not in GLOBAL_ROLES and any(b['id']!=branch_id for b in cached['branches']):raise ValueError('Branch mismatch')
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(row[1])).total_seconds()
            except (ValueError,TypeError,KeyError):cached=None
        if cached is not None and not force and 0<=age<30:
            return cached,row[1],'cached'
        try:
            # Always issue the request: the existing 401 handler can refresh the same online identity.
            response=_request_with_auth_retry('GET','/dashboard/overview',timeout=8)
            if response.status_code in (401,403):
                if response.status_code==403:
                    conn.execute('DELETE FROM central_inventory_view_cache WHERE user_id=?',(user_id,));conn.commit()
                    return None,None,'denied'
                return cached,row[1] if cached else None,'authentication_required'
            response.raise_for_status()
            data=validate_snapshot(response.json(),role)
            if data.get('user_id')!=user_id:raise PermissionError('Central identity differs from session')
            if role not in GLOBAL_ROLES and any(b['id']!=branch_id for b in data['branches']):raise PermissionError('Central branch differs from session')
            stamp=datetime.now(timezone.utc).isoformat(timespec='seconds')
            conn.execute('INSERT INTO central_inventory_view_cache(user_id,payload,fetched_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET payload=excluded.payload,fetched_at=excluded.fetched_at',(user_id,json.dumps(data,ensure_ascii=False),stamp));conn.commit()
            return data,stamp,'online'
        except PermissionError:
            return None,None,'denied'
        except Exception:
            conn.rollback()
        return cached,row[1] if cached else None,'offline'
    finally:conn.close()


def render_alerts(data,selected_ids):
    import streamlit as st
    alerts=[r for r in data.get('alerts',[]) if r['branch_id'] in selected_ids]
    names={b['id']:b['branch_name'] for b in data['branches']}
    st.markdown('### 🔔 تنبيهات المخزون')
    kinds=('expired','expiry_7','expiry_30','low_stock')
    labels=('🔴 منتهي الصلاحية','🟠 خلال 7 أيام','🟡 خلال 30 يوماً','📉 أقل من الحد المحدد')
    for col,kind,label in zip(st.columns(4),kinds,labels):col.metric(label,sum(r['type']==kind for r in alerts))
    expired=[r for r in alerts if r['type']=='expired']
    if expired:st.error(f'🚨 يوجد {len(expired)} دفعة منتهية الصلاحية وبها رصيد متبقٍ.')
    expiry=[r for r in alerts if r['type']!='low_stock']
    if expiry:
        with st.expander('عرض تفاصيل تنبيهات الصلاحية',expanded=bool(expired)):
            for row in expiry:
                days=row['days_left'];status=f'🔴 منتهي منذ {abs(days)} يوم' if days<0 else ('🔴 ينتهي اليوم' if days==0 else f'متبقي {days} يوم')
                st.write(f"**{row['item_name']}** — {row['item_code']} | {names[row['branch_id']]} | المتبقي: **{row['quantity']:g}** | {row['expiry_date']} | {status}")
    low=[r for r in alerts if r['type']=='low_stock']
    if low:
        with st.expander('عرض تفاصيل تنبيهات انخفاض الرصيد',expanded=True):
            for row in low:st.write(f"📉 **{row['item_name']}** — {row['item_code']} | {names[row['branch_id']]} | المتبقي: **{row['quantity']:g}** | الحد: {row['threshold']:g}")


def selected_snapshot(data, selected):
    if selected is None and data.get('scope')=='branch' and {int(b['id']) for b in data['branches']}=={7}:selected=7
    ids=report_branch_ids((b['id'] for b in data['branches']), selected)
    return ids,[r for r in data['items'] if r['branch_id'] in ids],[r for r in data.get('metrics',[]) if r['branch_id'] in ids]


def render_dashboard(username,role,branch_id=None):
    import streamlit as st
    st.markdown("""<style>
    .az-dashboard-title{direction:rtl;text-align:right;width:100%;font-weight:850;font-size:22px;color:#1e293b;margin:15px 0 12px}
    [data-testid="stMetric"]{direction:rtl;text-align:right}
    [data-testid="stMetricLabel"],[data-testid="stMetricValue"]{direction:rtl;text-align:right;justify-content:flex-start}
    [data-testid="stMetricValue"] > div{direction:ltr;unicode-bidi:isolate;text-align:right}
    .az-intro{direction:rtl;text-align:right;padding:9px 14px;background:#ecfdf5;border-right:4px solid #16a34a;border-radius:7px;margin-bottom:12px}
    .az-branch{direction:rtl;text-align:right;font-weight:800;font-size:18px;margin:5px 0 8px}
    </style>""",unsafe_allow_html=True)
    from views.company_brand import company_label
    st.markdown(f'<div class="az-intro">☕ {company_label()} — أهلاً {html.escape(str(username))} | لوحة البيانات المركزية</div>',unsafe_allow_html=True)
    force=st.button('تحديث بيانات كل الفروع' if role in GLOBAL_ROLES else 'تحديث بيانات الفرع',key='central_inventory_refresh')
    try:data,stamp,state=load_overview(st.session_state.get('user_id'),role,force,branch_id)
    except Exception:
        st.error('تعذر قراءة لوحة البيانات المركزية؛ لن نعرض بيانات نقطة البيع كأنها إجمالي السيرفر.');return
    if data is None:
        st.warning('يلزم تأكيد دخول المستخدم أونلاين لتنزيل لوحة الفروع والتنبيهات لأول مرة.' if state=='authentication_required' else 'البيانات المركزية غير متاحة للحساب الحالي.');return
    st.caption('آخر مزامنة ناجحة للوحة والتنبيهات: '+datetime.fromisoformat(stamp).astimezone().strftime('%Y-%m-%d %H:%M:%S'))
    if state in ('online','cached'):st.caption('المرجع: بيانات السيرفر المركزية — تحديث تلقائي كل 30 ثانية.')
    else:st.warning('عرض آخر بيانات مركزية محفوظة؛ العمليات غير المتزامنة مش داخلة فيها.'+(' أكد الدخول أونلاين لاستعادة التحديث.' if state=='authentication_required' else ''))
    names={b['id']:b['branch_name'] for b in data['branches']}
    options=[None]+list(names)
    selected=st.selectbox('الفرع المعروض',options,format_func=lambda bid:'جميع الفروع' if bid is None else names[bid],key='central_dashboard_branch')
    ids,items,metrics=selected_snapshot(data,selected)
    from views.branch_sync_state import display_receipt_summary
    display_receipt_summary(data,ids)
    st.caption(f"الفروع المتاحة حسب صلاحية الحساب: {len(names)} | الفروع المعروضة: {len(ids)}")
    if role in ('Super_Admin','Admin','Manager','General_Supervisor','Branch_Supervisor'):render_alerts(data,ids)
    finances={r['branch_id']:r for r in metrics}
    def values(bid):
        rows=[r for r in items if r['branch_id']==bid];m=finances.get(bid,{})
        qty=sum(r['quantity'] for r in rows);cost=sum(r['quantity']*(r['avg_cost'] if r['avg_cost']>0 else r['buy_price']) for r in rows);retail=sum(r['quantity']*r['sale_price'] for r in rows)
        return dict(sales=m.get('sales',0),expenses=m.get('expenses',0),revenues=m.get('revenues',0),invoices=m.get('invoice_count',0),purchases=m.get('purchases',0),quantity=qty,cost=cost,retail=retail)
    def show_metrics(v):
        entries=[('💰 المبيعات',v['sales'],True),('🧾 عدد الفواتير',v['invoices'],False),('💸 المصروفات',v['expenses'],True),('💰 الإيرادات',v['sales']+v['revenues'],True),('📦 المخزون (مجموع كميات)',v['quantity'],False),('🏷️ المخزون بالتكلفة',v['cost'],True),('🛒 المخزون بالبيع',v['retail'],True),('📈 ربح المخزون المتوقع',v['retail']-v['cost'],True),('📥 المشتريات',v['purchases'],True)]
        for i in range(0,len(entries),3):
            for col,(label,value,money) in zip(st.columns(3),entries[i:i+3]):col.metric(label,f'{value:,.2f} د.ل' if money else f'{value:,.3f}'.rstrip('0').rstrip('.'))
    totals={key:sum(values(bid)[key] for bid in ids) for key in ('sales','expenses','revenues','invoices','purchases','quantity','cost','retail')}
    st.markdown('<div class="az-dashboard-title">📊 إجمالي المجموعة</div>',unsafe_allow_html=True);show_metrics(totals);st.divider()
    st.markdown('<div class="az-dashboard-title">🏢 الفروع والمخزن الرئيسي</div>',unsafe_allow_html=True)
    for bid,name in names.items():
        if bid not in ids:continue
        st.markdown(f'<div class="az-branch">🏢 {html.escape(str(name))}</div>',unsafe_allow_html=True);show_metrics(values(bid));st.divider()
    with st.expander('أرصدة الأصناف في الفروع'):
        st.dataframe([{'الفرع':names[r['branch_id']],'كود الصنف':r['item_code'],'الصنف':r['item_name'],'الوحدة':r['unit'],'الكمية':r['quantity']} for r in items],use_container_width=True,hide_index=True)
    for key,label in [('invoices','الفواتير'),('expenses','المصروفات')]:
        rows=[dict(r,branch_name=names[r['branch_id']]) for r in data.get('records',{}).get(key,[]) if r['branch_id'] in ids]
        if rows:
            with st.expander(label):st.dataframe(rows,use_container_width=True,hide_index=True)
    if data.get('records',{}).get('suppliers'):
        with st.expander('الموردون'):
            st.dataframe([{'المورد':r['supplier_name']} for r in data['records']['suppliers']],use_container_width=True,hide_index=True)
    st.caption('الإيرادات = الفواتير + الإيرادات اليدوية. الربح المتوقع يخص المخزون الحالي فقط، وليس صافي الربح. جمع الكميات عبر وحدات مختلفة مؤشر تقريبي.')


def show_central_inventory(role):
    import streamlit as st
    callback=st.fragment(run_every=30)(render_dashboard) if hasattr(st,'fragment') else render_dashboard
    callback(st.session_state.get('username',''),role,st.session_state.get('branch_id'))


def headquarters_context(require_headquarters=True):
    """Use existing approved device binding; never change enrollment or account role."""
    if os.name!='nt':return None
    import sqlite3
    from contextlib import closing
    from pathlib import Path
    root=Path(__file__).resolve().parent
    with closing(sqlite3.connect(__import__('sherif_paths').local_db().resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as conn:
        meta=dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('device_id','bound_device_id','bound_branch_id','device_active','server_enrolled')"))
        if (meta.get('device_id')!=meta.get('bound_device_id') or meta.get('device_active')!='1' or meta.get('server_enrolled')!='1'):
            return None
        bid=int(meta.get('bound_branch_id') or 0)
        branch=conn.execute('SELECT branch_name,branch_type FROM branches WHERE id=?',(bid,)).fetchone()
        name=branch[0] if branch else ''
        kind=branch[1] if branch else None
        # A central view cache can identify the already-bound branch even if the old catalog is incomplete.
        if kind is None:
            for row in conn.execute('SELECT payload FROM central_inventory_view_cache'):
                try:
                    match=next((b for b in json.loads(row[0])['branches'] if b['id']==bid),None)
                    if match:kind=match.get('branch_type');name=match.get('branch_name','');break
                except (ValueError,KeyError,TypeError):continue
        headquarters_names=('مخزن رئيسي','المخزن الرئيسي','مركز رئيسي','المركز الرئيسي')
        normalized=' '.join(str(name or '').split())
        if require_headquarters and kind not in headquarters_names and not (kind=='مخزن' and normalized in headquarters_names):return None
    from urllib.parse import urlsplit,urlunsplit
    from offline_store import _api_base_url
    address=urlsplit(_api_base_url())
    if address.scheme!='https' or not address.hostname or address.username or address.password:
        raise ValueError('Invalid central management address')
    return {'branch_id':bid,'url':urlunsplit((address.scheme,address.netloc,'/','',''))}


def headquarters_frontend(choice, menu_groups=None):
    """Original server screens online; original cached dashboard offline. No local central writes."""
    import streamlit as st
    if os.name!='nt' or st.session_state.get('role') not in GLOBAL_ROLES:return False
    # POS and its archive/shift views always use the authenticated local session.
    # Central management retains its separate server login and permissions.
    if choice.startswith('__') or choice in ('🛒 نقطة البيع (POS)','🤖 المساعد الذكي AI'):return False
    try:context=headquarters_context(require_headquarters=st.session_state.get('role') not in ('Super_Admin','Admin'))
    except Exception:
        st.error('تعذر التحقق من اعتماد جهاز المركز؛ تم منع فتح شاشة تعديل مركزية بأرصدة محلية.');return True
    if not context:return False
    import requests
    @st.cache_data(ttl=15,show_spinner=False)
    def reachable(url):
        try:return requests.get(url,timeout=4,allow_redirects=False).status_code==200
        except requests.RequestException:return False
    if not reachable(context['url']):
        st.warning('المركز الرئيسي غير متصل: التعديل المركزي متوقف بأمان. دي آخر بيانات ولوحة وتنبيهات محفوظة.')
        st.error('تعذر الاتصال بالإدارة المركزية حالياً. شاشة البيع المحلية متاحة.');return True
    if hasattr(st,'fragment'):
        @st.fragment(run_every=30)
        def refresh_central_cache():
            try:load_overview(st.session_state.get('user_id'),st.session_state.get('role'),True,st.session_state.get('branch_id'))
            except Exception:pass
        refresh_central_cache()
    from urllib.parse import urlencode
    entries=[entry for group in (menu_groups or {}).values() for entry in group if entry[0]==choice]
    allowed_keys={key for _,_,updates in entries for key in updates}
    modes={k:v for k,v in dict(st.session_state).items() if k in allowed_keys and isinstance(v,str) and any(updates.get(k)==v for _,_,updates in entries)}
    from offline_store import _request_with_auth_retry
    try:
        response=_request_with_auth_retry('POST','/admin/web-session',json={'user_id':int(st.session_state.get('user_id'))},timeout=8)
        response.raise_for_status();handoff=response.json()
        import re
        if handoff.get('user_id')!=st.session_state.get('user_id') or not re.fullmatch(r'[A-Za-z0-9_-]{43}',str(handoff.get('ticket',''))):
            raise PermissionError('Central identity mismatch')
    except Exception:
        st.error('تعذر فتح الإدارة المركزية للحساب الحالي. تحقق من الاتصال وصلاحية الدخول.');return True
    url=context['url']+'?'+urlencode({'az_bridge':'1','az_target':choice,'az_modes':json.dumps(modes,ensure_ascii=False,sort_keys=True)})+'#'+urlencode({'az_ticket':handoff['ticket']})
    # Display the existing server application, including its own authenticated menus.
    # Do not duplicate forms, send passwords/tokens in URLs or write central rows to POS SQLite.
    # Keep the Windows menu in control so its POS route always stays local.
    st.markdown('<style>.block-container{max-width:100%;padding-top:0}</style>',unsafe_allow_html=True)
    st.markdown('<style>html body [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:#f1f5f9!important}</style>',unsafe_allow_html=True)
    if st.button('العودة إلى البرنامج المحلي',key='central_return_local'):
        st.session_state['page']='🛒 نقطة البيع (POS)'
        st.session_state['pos_active_view']='الكاشير'
        st.rerun()
    import streamlit.components.v1 as components
    components.iframe(url,height=1300,scrolling=True)
    # The handoff is single-use and never duplicated into a second link.
    return True


def _central_web_actor(conn, user_id, device_id):
    """Revalidate the real account and approved headquarters device on the server."""
    from control_services import account_login_allowed, _control_execute
    user = _control_execute(conn, 'SELECT id,username,role,branch_id,is_active FROM users WHERE id=?', (user_id,)).fetchone()
    if not user or not user['is_active'] or user['role'] not in GLOBAL_ROLES or not account_login_allowed(conn, user_id):
        raise PermissionError('Central administration permission denied')
    device = _control_execute(conn, '''SELECT d.device_id,d.is_active,b.branch_name,b.branch_type
        FROM branch_devices d JOIN branches b ON b.id=d.branch_id WHERE d.device_id=?''', (device_id,)).fetchone()
    if not device or not device['is_active']:
        raise PermissionError('Approved device required')
    kinds=('مخزن رئيسي','المخزن الرئيسي','مركز رئيسي','المركز الرئيسي')
    name=' '.join(str(device['branch_name'] or '').split())
    if user['role']!='Super_Admin' and device['branch_type'] not in kinds and not (device['branch_type']=='مخزن' and name in kinds):
        raise PermissionError('Headquarters device required')
    return {'id':int(user['id']),'username':user['username'],'role':user['role'],'branch_id':user['branch_id']}


def _central_handoff_hash(ticket):
    import hashlib
    return hashlib.sha256(('abuzaid-central-web-v1:'+ticket).encode('ascii')).hexdigest()


def issue_central_web_handoff(conn, user_id, device_id, auth_db=None):
    """One-use 45-second handoff; no password or API bearer enters browser URLs."""
    import sqlite3,secrets,time
    from pathlib import Path
    user=_central_web_actor(conn,user_id,device_id)
    ticket=secrets.token_urlsafe(32);expires=int(time.time())+45
    path=Path(auth_db) if auth_db else __import__('sherif_paths').session_db()
    from contextlib import closing
    with closing(sqlite3.connect(path,timeout=5)) as sessions, sessions:
        # Existing session table only. Never create or migrate an operational schema.
        sessions.execute("DELETE FROM sessions WHERE connection_mode LIKE 'central_web_pending:%' AND expires_at<=?",(int(time.time()),))
        count=sessions.execute('SELECT COUNT(*) FROM sessions WHERE user_id=? AND connection_mode=? AND expires_at>?',(str(user_id),'central_web_pending:'+device_id,int(time.time()))).fetchone()[0]
        if count>=30:raise PermissionError('Too many pending central handoffs')
        sessions.execute('INSERT INTO sessions(token_hash,username,role,user_id,branch_id,connection_mode,expires_at) VALUES(?,?,?,?,?,?,?)',
            (_central_handoff_hash(ticket),user['username'],user['role'],str(user_id),None if user['branch_id'] is None else str(user['branch_id']),'central_web_pending:'+device_id,expires))
    return {'ticket':ticket,'expires_in':45,'user_id':int(user_id)}


def consume_central_web_handoff(conn, ticket, auth_db=None):
    import re,sqlite3,time
    from pathlib import Path
    if not isinstance(ticket,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',ticket):
        raise PermissionError('Invalid central handoff')
    path=Path(auth_db) if auth_db else __import__('sherif_paths').session_db()
    from contextlib import closing
    with closing(sqlite3.connect(path,timeout=5)) as sessions, sessions:
        sessions.execute('BEGIN IMMEDIATE')
        row=sessions.execute("SELECT user_id,connection_mode,expires_at FROM sessions WHERE token_hash=? AND connection_mode LIKE 'central_web_pending:%'",(_central_handoff_hash(ticket),)).fetchone()
        if not row or row[2]<=int(time.time()):raise PermissionError('Expired or consumed central handoff')
        device_id=row[1].split(':',1)[1]
        user=_central_web_actor(conn,int(row[0]),device_id)
        sessions.execute('DELETE FROM sessions WHERE token_hash=?',(_central_handoff_hash(ticket),))
    user['device_id']=device_id
    return user


def restore_central_web_session():
    """Called once at the common server entry, before its ordinary login form."""
    import streamlit as st
    if os.name=='nt':return
    marker=st.query_params.get('az_bridge')=='1'
    if not marker:return
    # Only the embedded server menu is hidden; the original Windows menu remains.
    st.markdown('<style>html body .stApp [data-testid="stSidebar"],html body .stApp [data-testid="stSidebarCollapsedControl"],html body .stApp [data-testid="stExpandSidebarButton"],html body .stApp [data-testid="collapsedControl"]{display:none!important}</style>',unsafe_allow_html=True)
    if st.session_state.get('_central_web_device'):
        from database import get_remote_connection
        conn=get_remote_connection()
        try:user=_central_web_actor(conn,st.session_state.get('user_id'),st.session_state['_central_web_device'])
        except PermissionError:
            st.session_state['logged_in']=False
            st.error('انتهى تصريح الإدارة المركزية. افتح الشاشة من البرنامج مجدداً.');st.stop()
        finally:conn.close()
        st.session_state.update(role=user['role'],username=user['username'],branch_id=user['branch_id'])
        return
    from streamlit.components.v2 import component
    @st.cache_resource(show_spinner=False)
    def bridge_component():
        return component('abuzaid_central_web_handoff_v1',js=r'''
        export default function({setStateValue}) {
          const key='__abuzaidCentralWebHandoffV1';
          if (!(key in window)) {
            const fragment=new URLSearchParams(window.location.hash.slice(1));
            window[key]=fragment.get('az_ticket') || '';
            if (window[key]) history.replaceState(null,'',location.pathname+location.search);
          }
          setStateValue('ticket',window[key]);
        }''')
    result=bridge_component()(key='central_web_handoff',height=0,default={'ticket':None},on_ticket_change=lambda:None)
    ticket=result.ticket
    if ticket is None:st.stop()
    from database import get_remote_connection
    conn=get_remote_connection()
    try:user=consume_central_web_handoff(conn,ticket)
    except PermissionError:
        st.error('تعذر اعتماد جلسة الإدارة. افتح الشاشة من قائمة البرنامج مجدداً.');st.stop()
    finally:conn.close()
    st.session_state.update(logged_in=True,user_id=user['id'],username=user['username'],role=user['role'],
        branch_id=user['branch_id'],connection_mode='central_postgresql',_reference_sync_done_this_login=True,
        _central_web_device=user['device_id'])

