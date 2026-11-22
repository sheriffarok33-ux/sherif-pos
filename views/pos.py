_PAGE_ERROR_UI_REVISION = 71
from views.page_guard import show_operation_error
from views.sales_invoice_a4 import show_invoice_a4, credit_balance_snapshot
from views.dashboard import _validated_role
from views.ui_feedback import ui_field, ui_form, ui_submit, notify_success, reset_page_fields, focus_barcode
from views.ui_common import back_button
from views.ui_common import item_alerts
import streamlit as st
import json
from datetime import datetime
from database import get_db_connection, ensure_pos_extensions_schema
from views.scoped_permissions import has_scoped_permission
from offline_store import get_pos_connection, get_local_connection, server_available, pending_count, sync_now, get_central_shift_summary, get_cached_central_shift_summary


def _commit_checkout_discount_while_typing():
    # Streamlit number_input normally sends typed values only on Enter/blur.
    # Commit this field after a short typing pause, without moving focus or
    # invoking the invoice-confirmation button.
    st.components.v1.html(r"""
<script>
(() => {
  const w = window.parent, d = w.document;
  if (w.__abuzaidDiscountTypingCleanup) w.__abuzaidDiscountTypingCleanup();
  let timer;
  const changed = event => {
    const input = event.target;
    if (!(input instanceof w.HTMLInputElement) || input.type !== 'number' ||
        !input.closest('[role="dialog"], [data-testid="stDialog"]')) return;
    const name = input.getAttribute('aria-label') || '';
    if (name !== 'قيمة الخصم (د.ل):' && name !== 'نسبة الخصم (%):') return;
    w.clearTimeout(timer);
    timer = w.setTimeout(() => {
      if (!input.isConnected || input.disabled || d.activeElement !== input ||
          input.value === '' || !input.validity.valid) return;
      input.dispatchEvent(new w.KeyboardEvent('keydown', {
        key: 'Enter', code: 'Enter', bubbles: true, cancelable: true
      }));
    }, 450);
  };
  d.addEventListener('input', changed, true);
  w.__abuzaidDiscountTypingCleanup = () => {
    w.clearTimeout(timer);
    d.removeEventListener('input', changed, true);
  };
})();
</script>
""", height=0, width=0)


# Short-lived cache for the POS connection indicator and admin checks.
# Manual synchronization continues to use its original uncached implementation.
@st.cache_data(ttl=10, show_spinner=False)
def _pos_server_reachable():
    from auto_sync import auto_sync_status
    return bool(auto_sync_status().get('server_reachable'))


# Keyboard-only cashier flow. This affects browser focus/clicks only;
# it does not touch checkout validation, invoice posting or synchronization.
def _cashier_checkout_keyboard():
    st.components.v1.html(r"""
<script>
(() => {
  const w = window.parent, d = w.document;
  if (w.__abuZaidCashierCleanup) w.__abuZaidCashierCleanup();
  if (w.__abuZaidCashierKeys) d.removeEventListener('keydown', w.__abuZaidCashierKeys, true);
  if (w.__abuZaidCashierObserver) w.__abuZaidCashierObserver.disconnect();
  const state = w.__abuZaidCheckoutState ||= {phase:'idle', edited:false, pending:false};
  let pendingTimer;
  const visible = el => el && el.isConnected !== false && el.getClientRects().length && !el.disabled;
  const label = el => (el.innerText || el.textContent || '').trim();
  const dialog = () => d.querySelector('[role="dialog"], [data-testid="stDialog"]');
  const button = (root, text) => Array.from(root.querySelectorAll('button')).find(el => visible(el) && label(el).includes(text));
  const paid = root => Array.from(root.querySelectorAll('input')).find(el => visible(el) && el.type === 'number' &&
    ((el.getAttribute('aria-label') || '').includes('المبلغ المدفوع') ||
     (el.closest('[data-testid="stNumberInput"]')?.innerText || '').includes('المبلغ المدفوع')));
  const busy = () => d.querySelector('.stApp')?.getAttribute('data-test-script-state') === 'running';
  const consume = e => {e.preventDefault(); e.stopImmediatePropagation();};
  const inspect = () => {
    const dlg = dialog();
    if (!dlg) { if (state.phase !== 'opening' && !state.pending && !busy()) Object.assign(state,{phase:'idle',pending:false,ack:false}); return; }
    const confirm = button(dlg,'تأكيد وإصدار الفاتورة');
    const ok = button(dlg,'موافق');
    if (ok && !confirm) {
      state.phase='success';state.pending=false;
      if (state.ack && !state.acked) {state.acked=true;state.ack=false;ok.click();}
      else if (!state.acked && !d.activeElement?.matches('input,textarea,select')) ok.focus({preventScroll:true});
      return;
    }
    if (!confirm) return;
    if (state.phase !== 'payment') {state.phase='payment';state.confirm=confirm;state.acked=false;}
    if (state.pending) {
      if (busy()) state.sawBusy=true;
      // A completed rerender with the payment dialog still present means the
      // existing Python validation rejected submission. Permit correction.
      if (!busy() && (state.confirm !== confirm || state.sawBusy) && performance.now()-state.sentAt>150) {
        state.pending=false;state.ack=false;state.sawBusy=false;
      }
      if (state.pending && !busy() && performance.now()-state.sentAt<=150) {
        clearTimeout(pendingTimer);pendingTimer=setTimeout(inspect,160-(performance.now()-state.sentAt));
      }
    }
    state.confirm=confirm;
    if (state.keyboardOpen && !state.focused && !state.edited) {
      const input=paid(dlg);if (input) {state.focused=true;input.focus({preventScroll:true});}
    }
    if (state.commit && !busy()) {state.commit=false;confirm.focus({preventScroll:true});}
  };
  const edited = e => {
    const dlg=dialog();
    if (e.isTrusted && dlg?.contains(e.target) && e.target.matches('input,textarea,select,[role="combobox"]')) state.edited=true;
  };
  const handler = e => {
    if (!e.isTrusted || e.altKey || e.ctrlKey || e.metaKey || e.isComposing) return;
    const dlg=dialog();
    if (e.repeat) {if ((e.key==='Enter' && dlg) || e.key==='F10') consume(e);return;}
    if (e.key==='F10' && !dlg) {
      const open=button(d,'دفع واعتماد الفاتورة');
      if (open) {consume(e);Object.assign(state,{phase:'opening',keyboardOpen:true,edited:false,focused:false,pending:false,ack:false,acked:false,sawBusy:false,commit:false});open.click();}
      return;
    }
    if (e.key!=='Enter' || !dlg) return;
    if (state.pending && state.phase!=='success') {consume(e);state.ack=true;return;}
    const confirm=button(dlg,'تأكيد وإصدار الفاتورة');
    if (confirm) {
      if (state.pending) {consume(e);state.ack=true;return;}
      const input=paid(dlg), active=d.activeElement;
      if (active?.matches('[role="combobox"],select,textarea') || d.querySelector('[role="listbox"]')) return;
      // Changed fields use native blur/commit, then the original confirmation
      // and all Python payment/reference/account validation, without defaults.
      if (state.edited && active===input) {
        consume(e);state.commit=true;input.blur();setTimeout(inspect,120);return;
      }
      if (active!==confirm && !(state.keyboardOpen && !state.edited && input)) return;
      consume(e);state.pending=true;state.sentAt=performance.now();state.confirm=confirm;state.sawBusy=busy();confirm.click();return;
    }
    const ok=button(dlg,'موافق');
    if (ok && !state.acked && !d.activeElement?.matches('input,textarea,select')) {
      consume(e);state.acked=true;ok.click();
    }
  };
  d.addEventListener('keydown',handler,true);d.addEventListener('input',edited,true);d.addEventListener('change',edited,true);
  const observer=new MutationObserver(inspect);
  observer.observe(d.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','data-test-script-state']});
  const timer=setTimeout(inspect,90);
  w.__abuZaidCashierKeys=handler;w.__abuZaidCashierObserver=observer;
  w.__abuZaidCashierCleanup=()=>{clearTimeout(timer);clearTimeout(pendingTimer);observer.disconnect();d.removeEventListener('keydown',handler,true);d.removeEventListener('input',edited,true);d.removeEventListener('change',edited,true);};
})();

</script>
""", height=0, width=0)


_real_pos_connection=get_pos_connection


def _pos_actor():
    from views.pos_policy import actor
    c=get_db_connection()
    try:return actor(c,st.session_state.get('user_id'))
    finally:c.close()


def get_pos_connection(*args,**kwargs):
    from views.pos_policy import connection
    return connection(st.session_state,get_db_connection,lambda:_real_pos_connection(*args,**kwargs))


def _pos_branch():return st.session_state.get('_pos_branch_id',st.session_state.get('branch_id'))


# ============================================================
# رقم الوردية
# ============================================================

def get_current_shift_number(conn,branch_id):
    # The isolated sale context has no financial closures. Read the authoritative
    # branch state without copying history into memory or changing a real shift.
    if getattr(conn, 'virtual_pos', False):
        source = get_db_connection()
        try:
            return get_current_shift_number(source, branch_id)
        finally:
            source.close()
    _ensure_shift_finance_schema(conn)
    from views.branch_shift_state import effective_current_shift
    return effective_current_shift(conn,branch_id)

@st.fragment(run_every='5s')
def _watch_current_shift(branch_id,shown_shift):
    if _pos_actor()['role']!='Cashier':return
    conn=None
    try:
        from views.branch_shift_state import effective_current_shift
        conn=get_local_connection(queue_writes=False)
        current=effective_current_shift(conn,branch_id)
        from views.branch_shift_state import sale_hold_reason
        shift_hold=sale_hold_reason(conn,branch_id,shown_shift)
        hold=conn.execute("SELECT 1 FROM local_meta WHERE key='branch_reset_guard'").fetchone()
        reset_row=conn.execute('SELECT value FROM local_meta WHERE key=?',('last_branch_reset:'+str(int(branch_id)),)).fetchone()
        reset_id=json.loads(reset_row[0])['reset_id'] if reset_row else None
    except Exception:return
    finally:
        if conn is not None:conn.close()
    if shift_hold or current!=shown_shift or hold or (reset_id and reset_id!=st.session_state.get('_pos_reset_seen')):st.rerun(scope='app')

@st.fragment(run_every='5s')
def _watch_branch_admin_hold():
    conn=get_local_connection(queue_writes=False)
    try:hold=conn.execute("SELECT 1 FROM local_meta WHERE key='branch_reset_guard'").fetchone()
    finally:conn.close()
    if not hold:st.rerun(scope='app')



# ============================================================
# تجهيز السلة
# ============================================================

def _can_use_sale_draft(conn, branch_id):
    owner = _pos_actor()
    if owner['role'] == 'Cashier': return True
    if owner['role'] != 'Super_Admin': return False
    from sherif_local_identity import authorized_branch
    try: return authorized_branch(conn, owner['id'])['branch_id'] == int(branch_id)
    except (PermissionError, ValueError, TypeError): return False


def _bind_sale_draft(conn, branch_id):
    if not _can_use_sale_draft(conn, branch_id): return
    reset_row=conn.execute('SELECT value FROM local_meta WHERE key=?',('last_branch_reset:'+str(int(branch_id)),)).fetchone()
    reset_id=json.loads(reset_row[0])['reset_id'] if reset_row else None
    if reset_id and st.session_state.get('_pos_reset_seen')!=reset_id:
        for key in ('_sale_draft_scope','_sale_draft_record','pos_success_pending','pos_success_message','_sale_draft_save_failed'):
            st.session_state.pop(key,None)
        st.session_state['cart']=[];st.session_state['last_invoice']=None
        st.session_state['pos_active_view']='الكاشير السريع';st.session_state['pos_focus_barcode']=True
        st.session_state['_pos_reset_seen']=reset_id
    from offline_store import sale_draft_scope, read_sale_draft
    scope = sale_draft_scope(conn, branch_id, st.session_state.get('user_id'))
    if st.session_state.get('_sale_draft_scope') == scope:
        return
    prior_scope = st.session_state.get('_sale_draft_scope')
    draft = read_sale_draft(conn, scope)
    old_cart = st.session_state.get('cart', []) if prior_scope is None else []
    # Invoice preview belongs only to a sale completed in this live session.
    # Durable completed drafts prevent duplicate posting; they are not UI state.
    st.session_state['last_invoice'] = None
    st.session_state.pop('pos_success_pending', None)
    st.session_state.pop('pos_success_message', None)
    st.session_state['pos_active_view'] = 'الكاشير السريع'
    st.session_state['pos_focus_barcode'] = True
    st.session_state['_sale_draft_scope'] = scope
    st.session_state['_sale_draft_record'] = draft if draft and draft['state'] == 'open' else None
    st.session_state['cart'] = draft.get('cart', []) if draft and draft['state'] == 'open' else old_cart
    # A committed draft is never restored as a sellable cart after an interrupted UI.
    if draft and draft['state'] == 'completed':
        st.session_state['cart'] = []
    if not draft and old_cart:
        _persist_sale_draft()


def _persist_sale_draft():
    _validated_role()
    from offline_store import sale_draft_scope, save_sale_draft
    conn = get_local_connection()
    try:
        if not _can_use_sale_draft(conn, _pos_branch()): return
        scope = sale_draft_scope(conn, _pos_branch(), st.session_state.get('user_id'))
        if st.session_state.get('_sale_draft_scope') != scope:
            raise ValueError('تغير مالك السلة؛ أعد فتح شاشة البيع قبل تعديلها')
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('BEGIN IMMEDIATE')
        record = save_sale_draft(conn, scope, st.session_state.get('cart', []),
                                 st.session_state.get('_sale_draft_record'),
                                 original_shift=get_current_shift_number(conn,scope['branch_id']))
        conn.commit()
        st.session_state['_sale_draft_record'] = record
        st.session_state.pop('_sale_draft_save_failed', None)
    except Exception:
        conn.rollback()
        st.session_state['_sale_draft_save_failed'] = True
        raise ValueError('تعذر حفظ تعديل السلة على القرص؛ أعد المحاولة ولا تغلق البرنامج قبل نجاح الحفظ')
    finally:
        conn.close()


def _claim_cashier_draft(conn, branch_id):
    if getattr(conn,"virtual_pos",False):return None,{"state":"open"}
    from offline_store import sale_draft_scope, claim_sale_draft
    scope = sale_draft_scope(conn, branch_id, st.session_state.get('user_id'))
    if st.session_state.get('_sale_draft_scope') != scope or st.session_state.get('_sale_draft_save_failed'):
        raise ValueError('يلزم حفظ السلة والتحقق من مالكها قبل البيع')
    if conn.in_transaction:
        raise ValueError('توجد عملية حفظ أخرى؛ أعد المحاولة قبل اعتماد البيع')
    conn.execute('PRAGMA synchronous=FULL')
    conn.execute('BEGIN IMMEDIATE')
    owner=conn.execute('SELECT role,branch_id,is_active FROM users WHERE id=?',(st.session_state.get('user_id'),)).fetchone()
    if not owner or not owner['is_active'] or not _can_use_sale_draft(conn,branch_id):raise PermissionError('تغير تصريح البيع؛ لم تُسجل فاتورة حقيقية')
    if owner['role']=='Cashier' and int(owner['branch_id'] or -1)!=int(branch_id):raise PermissionError('تغير فرع الكاشير؛ لم تُسجل فاتورة حقيقية')
    from views.branch_shift_state import sale_hold_reason
    reason=sale_hold_reason(conn,branch_id,(st.session_state.get('_sale_draft_record') or {}).get('original_shift'))
    if reason:raise ValueError(reason)
    draft = claim_sale_draft(conn, scope, st.session_state.get('_sale_draft_record'), st.session_state['cart'])
    return scope, draft


def ensure_cart():
    if "cart" not in st.session_state:
        st.session_state["cart"] = []


# ============================================================
# دفعات الصلاحية والصرف بطريقة FEFO
# ============================================================

def ensure_inventory_batches_table(conn):
    """
    تجهيز جدول دفعات الصلاحية فقط إذا لم يكن موجوداً.
    لا يغيّر منطق POS الحالي ولا بيانات الفواتير.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_batches
        (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            branch_id INTEGER NOT NULL,
            quantity NUMERIC DEFAULT 0,
            remaining_quantity NUMERIC DEFAULT 0,
            received_date DATE DEFAULT CURRENT_DATE,
            expiry_date DATE,
            unit_cost NUMERIC DEFAULT 0,
            source_type TEXT DEFAULT 'inventory',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE,
            FOREIGN KEY (branch_id) REFERENCES branches(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_inventory_batches_expiry
        ON inventory_batches(branch_id, expiry_date)
        """
    )


def get_expired_tracked_quantity(conn, item_id, branch_id):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(remaining_quantity), 0) AS expired_qty
        FROM inventory_batches
        WHERE item_id = ?
          AND branch_id = ?
          AND COALESCE(remaining_quantity, 0) > 0
          AND expiry_date IS NOT NULL
          AND expiry_date < CURRENT_DATE
        """,
        (item_id, branch_id)
    ).fetchone()

    return float(row["expired_qty"] or 0) if row else 0.0


def get_low_stock_after_sale_alerts(conn, branch_id, cart, threshold=5.0):
    """حساب الأصناف التي سيصبح رصيدها المتاح 5 أو أقل بعد الفاتورة."""
    alerts = []

    try:
        item_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(items)").fetchall()
        }
    except Exception:
        item_cols = set()

    has_unit_type = "unit_type" in item_cols

    for cart_item in cart:
        if cart_item.get("id") == 99999:
            continue

        select_unit = ", unit_type" if has_unit_type else ""
        row = conn.execute(
            f"""
            SELECT id, item_name, quantity {select_unit}
            FROM items
            WHERE id = ? AND branch_id = ?
            """,
            (cart_item["id"], branch_id)
        ).fetchone()

        if not row:
            continue

        total_qty = float(row["quantity"] or 0)
        expired_qty = get_expired_tracked_quantity(
            conn, cart_item["id"], branch_id
        )
        available_before = max(0.0, total_qty - expired_qty)
        requested_qty = float(cart_item.get("qty", 0) or 0)
        remaining_after = available_before - requested_qty

        # لا نكرر هنا رسالة "الكمية غير كافية"؛ لها تحقق مستقل عند التأكيد.
        if 0 <= remaining_after <= float(threshold):
            unit_type = (
                str(row["unit_type"] or "").strip().lower()
                if has_unit_type else ""
            )
            kg_units = {
                "kg", "kilo", "kilogram", "weight",
                "وزن", "كيلو", "كجم"
            }
            unit_label = "كجم" if unit_type in kg_units else "قطعة"

            alerts.append({
                "name": cart_item.get("name") or row["item_name"],
                "remaining": remaining_after,
                "unit": unit_label,
            })

    return alerts


def get_item_stock_expiry_alert(conn, item_id, branch_id, cart_qty, threshold=5.0):
    """تنبيه لحظي للصنف في أي موقع/فرع، بما في ذلك المخزن الرئيسي."""
    item_cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    unit_select = ", unit_type" if "unit_type" in item_cols else ""
    item = conn.execute(
        f"SELECT item_name, quantity {unit_select} FROM items WHERE id=? AND branch_id=?",
        (item_id, branch_id)
    ).fetchone()
    if not item:
        return None

    total_qty = float(item["quantity"] or 0)
    expired_qty = get_expired_tracked_quantity(conn, item_id, branch_id)
    available_before = max(0.0, total_qty - expired_qty)
    remaining_after = available_before - float(cart_qty or 0)

    unit_type = str(item["unit_type"] or "").strip().lower() if "unit_type" in item_cols else ""
    kg_units = {"kg", "kilo", "kilogram", "weight", "وزن", "كيلو", "كجم"}
    unit_label = "كجم" if unit_type in kg_units else "قطعة"

    expiry_rows = conn.execute(
        """
        SELECT expiry_date, remaining_quantity,
               CAST(julianday(date(expiry_date)) - julianday(date('now','localtime')) AS INTEGER) AS days_left
        FROM inventory_batches
        WHERE item_id=? AND branch_id=?
          AND COALESCE(remaining_quantity,0) > 0
          AND expiry_date IS NOT NULL
          AND TRIM(CAST(expiry_date AS TEXT)) <> ''
          AND date(expiry_date) <= date('now','localtime','+30 days')
        ORDER BY date(expiry_date) ASC
        """,
        (item_id, branch_id)
    ).fetchall()

    low_stock = 0 <= remaining_after <= float(threshold)
    if not low_stock and not expiry_rows:
        return None

    return {
        "name": item["item_name"],
        "remaining_after": remaining_after,
        "unit": unit_label,
        "low_stock": low_stock,
        "expiry_rows": [dict(r) for r in expiry_rows],
    }


@st.dialog("🚨 تنبيه مخزون وصلاحية", width="large", dismissible=False)
def stock_expiry_warning_dialog(alert):
    _validated_role()
    st.error("⚠️ تنبيه مهم — يرجى مراجعة حالة الصنف قبل متابعة العمل.")

    if alert.get("low_stock"):
        st.warning(
            f"📉 **انخفاض المخزون:** بعد الكمية الموجودة بالفاتورة سيصبح رصيد "
            f"**{alert['name']}** حوالي **{alert['remaining_after']:,.3f} {alert['unit']}**."
        )

    for batch in alert.get("expiry_rows", []):
        days = int(batch.get("days_left") or 0)
        qty = float(batch.get("remaining_quantity") or 0)
        exp = batch.get("expiry_date")
        if days < 0:
            st.error(
                f"🔴 **دفعة منتهية الصلاحية:** {alert['name']} — "
                f"الكمية {qty:,.3f} — انتهت بتاريخ {exp}."
            )
        elif days == 0:
            st.error(
                f"🔴 **تنتهي اليوم:** {alert['name']} — "
                f"الكمية {qty:,.3f} — تاريخ الانتهاء {exp}."
            )
        elif days <= 7:
            st.warning(
                f"🟠 **صلاحية قريبة جدًا:** {alert['name']} — "
                f"الكمية {qty:,.3f} — متبقي {days} يوم — {exp}."
            )
        else:
            st.info(
                f"🟡 **صلاحية قريبة:** {alert['name']} — "
                f"الكمية {qty:,.3f} — متبقي {days} يوم — {exp}."
            )

    st.caption("هذا التنبيه يظهر لكل المواقع والفروع، بما فيها المخزن الرئيسي.")
    if st.button("✅ فهمت التنبيه", type="primary", use_container_width=True):
        st.session_state.pop("pos_stock_alert", None)
        st.session_state["pos_focus_barcode"] = True
        st.rerun()


def deduct_batches_fefo(conn, item_id, branch_id, requested_qty):
    """
    يخصم من الدفعات غير المنتهية ذات تاريخ الصلاحية الأقرب أولاً.
    الكمية القديمة التي لم تكن مسجلة كدفعة تبقى متاحة كرصيد legacy.
    """
    remaining_to_deduct = float(requested_qty)

    batches = conn.execute(
        """
        SELECT id, remaining_quantity, expiry_date
        FROM inventory_batches
        WHERE item_id = ?
          AND branch_id = ?
          AND COALESCE(remaining_quantity, 0) > 0
          AND (
                expiry_date IS NULL
                OR expiry_date >= CURRENT_DATE
              )
        ORDER BY
            CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END,
            expiry_date ASC NULLS LAST,
            id ASC
        FOR UPDATE
        """,
        (item_id, branch_id)
    ).fetchall()

    for batch in batches:
        if remaining_to_deduct <= 0:
            break

        batch_remaining = float(batch["remaining_quantity"] or 0)
        if batch_remaining <= 0:
            continue

        deducted = min(batch_remaining, remaining_to_deduct)

        conn.execute(
            """
            UPDATE inventory_batches
            SET remaining_quantity = remaining_quantity - ?
            WHERE id = ?
            """,
            (deducted, batch["id"])
        )

        remaining_to_deduct -= deducted

    # أي كمية متبقية هنا تخص مخزوناً قديماً لم يكن مسجلاً كدفعات.
    return max(0.0, remaining_to_deduct)


# ============================================================
# إضافة صنف غير موجود
# ============================================================

@st.dialog("⚠️ صنف غير مسجل - إضافة سريعة", dismissible=False)
def add_missing_item_dialog(scanned_code, b_id):

    _validated_role()
    st.warning(
        f"الكود ({scanned_code}) غير موجود في هذا الفرع. "
        "يمكنك إضافته وبيعه فوراً."
    )

    with ui_form("quick_add_missing_item_form"):

        new_item_name = ui_field(st.text_input, "pos:299", 
            "اسم الصنف:"
        )

        col_q1, col_q2 = st.columns(2)

        with col_q1:
            new_item_qty = ui_field(st.number_input, "pos:306", 
                "الكمية:",
                min_value=0.01,
                value=1.0,
                step=1.0
            )

        with col_q2:
            new_item_price = ui_field(st.number_input, "pos:314", 
                "سعر البيع (د.ل):",
                min_value=0.0,
                value=0.0,
                step=0.5,
                format="%.2f"
            )

        submitted = ui_submit(
            "💾 إضافة للسلة ومتابعة البيع",
            type="primary"
        )

    if st.button("إلغاء والعودة للباركود", key="pos_missing_cancel"):
        st.session_state.pop("pos_missing_item", None)
        st.session_state["pos_focus_barcode"] = True
        st.rerun()

    if not submitted:
        return

    if (
        not new_item_name.strip()
        or new_item_price <= 0
    ):
        st.error(
            "⚠️ يرجى إدخال اسم الصنف "
            "وسعر بيع صحيح."
        )
        return

    conn = None

    try:
        conn, _pos_mode = get_pos_connection(actor_id=st.session_state.get('user_id'))

        if conn.execute("SELECT 1 FROM local_meta WHERE key='branch_reset_guard'").fetchone():
            st.warning('يوجد إجراء إداري معتمد للفرع قيد الاستكمال. بياناتك المعلقة محفوظة؛ راجع المسؤول قبل البيع.')
            _watch_branch_admin_hold()
            return

        if _pos_mode in ("offline", "local"):
            st.warning("🟠 إضافة صنف جديد من نقطة البيع غير متاحة في وضع Local-first. استخدم الأصناف التي تم تنزيلها مسبقًا، ثم أضف الصنف الجديد بعد عودة الاتصال.")
            return

        existing = conn.execute(
            """
            SELECT id
            FROM items
            WHERE branch_id = ?
              AND item_code = ?
            """,
            (
                b_id,
                scanned_code
            )
        ).fetchone()

        if existing:
            new_item_id = existing["id"]

        else:
            # PostgreSQL:
            # RETURNING id بدلاً من lastrowid
            row = conn.execute(
                """
                INSERT INTO items
                (
                    branch_id,
                    item_code,
                    item_name,
                    quantity,
                    buy_price,
                    sale_price,
                    avg_cost
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    b_id,
                    scanned_code,
                    new_item_name.strip(),
                    float(new_item_qty),
                    0.0,
                    new_item_price,
                    0.0
                )
            ).fetchone()

            new_item_id = row["id"]

        conn.commit()

        ensure_cart()

        st.session_state["cart"].append(
            {
                "id": new_item_id,
                "code": scanned_code,
                "name": new_item_name.strip(),
                "price": float(new_item_price),
                "qty": float(new_item_qty),
                "total": (
                    float(new_item_price)
                    * float(new_item_qty)
                )
            }
        )

        _persist_sale_draft()
        st.session_state.pop("pos_missing_item", None)
        notify_success(
            "✅ تمت إضافة الصنف للسلة."
        )

        st.rerun()

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ تعذر إضافة الصنف."
        )

        show_operation_error(e, announce=False, context='views/pos.py:715')

    finally:

        if conn:
            conn.close()


# ============================================================
# شاشة الدفع والخصم
# ============================================================

@st.dialog("✅ تمت العملية بنجاح", dismissible=False)
def _pos_success_dialog():
    # Keep keyboard handler mounted while the success dialog is open.
    # The main cashier page stops rendering during this dialog.
    _validated_role()
    _cashier_checkout_keyboard()
    st.success(
        st.session_state.get(
            "pos_success_message",
            "تم إصدار الفاتورة بنجاح."
        )
    )
    st.info("تم حفظ الفاتورة. اضغط «موافق» للانتقال مباشرة إلى بيع جديد.")

    # الطباعة/التحميل اختياريان؛ لا يعطلان دورة البيع السريعة.
    inv = st.session_state.get("last_invoice")
    if inv:
        html_file_content = build_invoice_print_html(inv)
        show_invoice_a4(inv, key='a4_saved_1_'+str(inv['inv_id']))
        st.components.v1.html(
            html_file_content,
            height=330,
            scrolling=True
        )
        st.download_button(
            "📥 تحميل الفاتورة (HTML)",
            data=html_file_content.encode("utf-8"),
            file_name=f"Invoice_{inv['inv_id']}.html",
            mime="text/html",
            use_container_width=True,
            key="pos_success_download_invoice"
        )

    if st.button(
        "موافق",
        type="primary",
        use_container_width=True,
        key="pos_success_ok"
    ):
        # تنظيف بيانات العملية السابقة وبدء فاتورة جديدة فوراً.
        reset_page_fields()
        st.session_state["cart"] = []
        for key in [
            "pos_customer_name",
            "pos_customer_phone",
            "pos_marketing_consent",
            "pos_customer_name_input",
            "pos_customer_phone_input",
            "pos_marketing_consent_input",
            "pos_show_customer_data",
        ]:
            st.session_state.pop(key, None)
        st.session_state.pop("pos_success_pending", None)
        st.session_state.pop("pos_success_message", None)
        # لا نعرض آخر فاتورة داخل شاشة الكاشير بعد الضغط على موافق؛
        # تظل الفاتورة محفوظة في الأرشيف ويمكن إعادة طباعتها لاحقاً.
        st.session_state["last_invoice"] = None
        # بعد إعادة الرسم سنعيد المؤشر مباشرة إلى حقل الباركود.
        st.session_state["pos_focus_barcode"] = True
        st.rerun()


@st.dialog("💳 إتمام الدفع وإصدار الفاتورة")
def checkout_payment_dialog(
    b_id,
    gross_total,
    branch_name_str,
    cashier_name_str,
    shift_num,
    daily_inv_num
):

    _validated_role()
    _cashier_checkout_keyboard()
    st.subheader(
        f"إجمالي الفاتورة قبل الخصم: "
        f"{gross_total:,.2f} د.ل"
    )

    cust_name = ui_field(st.text_input, "pos:512", 
        "اسم الزبون:",
        value=st.session_state.get("pos_customer_name", "زبون نقدي")
    )

    cust_phone = ui_field(st.text_input, "pos:517", 
        "رقم الهاتف (اختياري):",
        value=st.session_state.get("pos_customer_phone", "")
    )

    marketing_consent = ui_field(st.checkbox, "pos:522", 
        "يوافق العميل على استقبال العروض والرسائل التسويقية",
        value=bool(st.session_state.get("pos_marketing_consent", False))
    )

    # ========================================================
    # الخصم
    # ========================================================

    st.markdown("### 🎁 خصم على الفاتورة")

    # Register the mode with the existing rerun preservation/success reset.
    discount_type = ui_field(st.radio, "pos:discount_mode",
        "طريقة الخصم:",
        [
            "بدون خصم",
            "خصم بمبلغ",
            "خصم بنسبة %"
        ],
        horizontal=True
    )

    discount_value = 0.0
    discount_amount = 0.0

    if discount_type == "خصم بمبلغ":

        # The old generated widget identity included the changing gross total.
        # Keep one identity across redraws and preserve the current entered value.
        amount_key = "_entry_pos:548_amount"
        if amount_key not in st.session_state:
            previous_keys = [k for k in st.session_state.get("_entry_fields", {})
                             if k.startswith("_entry_pos:548_") and k in st.session_state]
            st.session_state[amount_key] = float(st.session_state[previous_keys[-1]]) if previous_keys else 0.0
        discount_value = ui_field(st.number_input, "pos:548",
            "قيمة الخصم (د.ل):",
            key=amount_key,
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.2f"
        )

        discount_amount = float(
            discount_value
        )

    elif discount_type == "خصم بنسبة %":

        discount_value = ui_field(st.number_input, "pos:563", 
            "نسبة الخصم (%):",
            min_value=0.0,
            max_value=100.0,
            value=0.0,
            step=1.0,
            format="%.2f"
        )

        discount_amount = (
            float(gross_total)
            * float(discount_value)
            / 100.0
        )

    if discount_type != "بدون خصم":
        _commit_checkout_discount_while_typing()

    discount_amount = min(
        discount_amount,
        float(gross_total)
    )

    final_tot = max(
        0.0,
        float(gross_total)
        - discount_amount
    )

    # ========================================================
    # عرض الحسبة
    # ========================================================
    # Keep amounts legible inside the narrow checkout dialog, including RTL.
    st.markdown("""
    <style>
    [data-testid="stDialog"] [data-testid="stMetricValue"] {
        font-size: clamp(0.95rem, 2.5vw, 1.35rem) !important;
        line-height: 1.45 !important;
        overflow: visible !important;
        text-overflow: clip !important;
        white-space: nowrap !important;
        letter-spacing: -0.025em !important;
    }
    [data-testid="stDialog"] [data-testid="stMetric"] {
        min-width: 0 !important;
    }
    @media (max-width: 600px) {
        [data-testid="stDialog"] [data-testid="stMetricValue"] {
            font-size: 0.95rem !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    c_total1, c_total2, c_total3 = (
        st.columns(3)
    )

    c_total1.metric(
        "الإجمالي",
        f"{gross_total:,.2f} د.ل"
    )

    c_total2.metric(
        "الخصم",
        f"{discount_amount:,.2f} د.ل"
    )

    c_total3.metric(
        "الصافي",
        f"{final_tot:,.2f} د.ل"
    )

    if (
        discount_type == "خصم بنسبة %"
        and discount_value > 0
    ):
        st.success(
            f"🎁 خصم {discount_value:,.2f}% "
            f"= {discount_amount:,.2f} د.ل"
        )

    elif (
        discount_type == "خصم بمبلغ"
        and discount_amount > 0
    ):
        st.success(
            f"🎁 تم تطبيق خصم "
            f"{discount_amount:,.2f} د.ل"
        )

    st.markdown("---")

    # ========================================================
    # الدفع
    # ========================================================

    pay_method = ui_field(st.selectbox, "pos:657", 
        "نوع الدفع:",
        [
            "كاش (نقدي)",
            "شبكة / بطاقة",
            "تحويل مصرفي",
            "دفع آخر",
            "آجل (على الحساب)"
        ]
    )

    conn = None
    _pos_priority_held = False
    accounts = []
    selected_account_id = None

    try:
        conn, _pos_mode = get_pos_connection(actor_id=st.session_state.get('user_id'))

        if pay_method == "آجل (على الحساب)":

            from views.party_reference import credit_accounts
            accounts = credit_accounts(conn)
            from views.scale_quantity import credit_freshness
            freshness=credit_freshness(conn)
            if freshness:st.caption(freshness)

            if accounts:

                acc_opts = {
                    (
                        f"{a['customer_name']} "
                        f"({a['phone'] or '-'}) "
                        f"- المديونية: "
                        f"{float(a['balance'] or 0):,.2f} د.ل"
                    ): a["id"]

                    for a in accounts
                }

                sel_acc_str = ui_field(st.selectbox, "pos:702", 
                    "📌 اختر الزبون الآجل:",
                    list(acc_opts.keys())
                )

                selected_account_id = (
                    acc_opts[sel_acc_str]
                )

                # عند اختيار زبون آجل مسجل نعتمد اسمه الحقيقي في الفاتورة والطباعة،
                # بدلاً من بقاء الاسم الافتراضي "زبون نقدي".
                selected_account = next(
                    (
                        a for a in accounts
                        if a["id"] == selected_account_id
                    ),
                    None
                )
                if selected_account:
                    cust_name = str(
                        selected_account["customer_name"] or ""
                    ).strip() or "زبون نقدي"
                    cust_phone = str(
                        selected_account["phone"] or ""
                    ).strip()

            else:
                st.error(
                    "⚠️ لا يوجد زبائن آجلون "
                    "مسجلون في النظام."
                )

        # ====================================================
        # المبلغ المدفوع
        # ====================================================

        if pay_method == "آجل (على الحساب)":

            paid_amount = 0.0

            st.info(
                f"📌 سيتم تسجيل "
                f"{final_tot:,.2f} د.ل "
                "على حساب الزبون."
            )

        else:

            paid_amount = ui_field(st.number_input, "pos:750", 
                "المبلغ المدفوع (د.ل):",
                min_value=0.0,
                value=float(final_tot),
                step=0.5,
                format="%.2f"
            )

            change_due = (
                float(paid_amount)
                - float(final_tot)
            )
            # Ignore binary-float noise only; a real monetary shortfall still fails.
            if abs(change_due) <= 1e-9:
                change_due = 0.0

            if change_due >= 0:

                st.success(
                    f"💵 الباقي للزبون: "
                    f"**{change_due:,.2f} د.ل**"
                )

            else:

                st.error(
                    f"⚠️ المبلغ غير كافٍ. "
                    f"العجز: "
                    f"**{abs(change_due):,.2f} د.ل**"
                )

        # ====================================================
        # تأكيد الفاتورة
        # ====================================================

        confirm_invoice = st.button(
            "🖨️ تأكيد وإصدار الفاتورة",
            type="primary",
            use_container_width=True
        )

        if not confirm_invoice:
            return

        from offline_store import begin_pos_priority
        begin_pos_priority()
        _pos_priority_held = True
        owner=_pos_actor()
        if owner['role']=='Cashier':
            from views.branch_shift_state import registered_pos_branch
            if registered_pos_branch(conn,owner['id'])[0]!=int(b_id):raise PermissionError('البيع الحقيقي مقصور على فرع الكاشير والجهاز المسجل')
        elif not getattr(conn,'virtual_pos',False):
            if owner['role']!='Super_Admin':raise PermissionError('تعذر اعتماد سياق POS لهذا الحساب؛ أعد فتح شاشة البيع')
            from sherif_local_identity import authorized_branch
            if authorized_branch(conn,owner['id'])['branch_id']!=int(b_id):raise PermissionError('البيع خارج فرع الجهاز غير مسموح')

        if (
            pay_method == "آجل (على الحساب)"
            and not selected_account_id
        ):
            st.error(
                "⚠️ يجب اختيار الزبون الآجل."
            )
            return

        if (
            pay_method != "آجل (على الحساب)"
            and change_due < 0.0
        ):
            st.warning(
                "⚠️ المبلغ المدفوع أقل "
                "من إجمالي الفاتورة."
            )
            return

        owner=_pos_actor()
        if owner['role']=='Cashier' and getattr(conn,'virtual_pos',False):raise PermissionError('تغير سياق البيع؛ أعد فتح شاشة POS')
        if owner['role']!='Cashier' and not getattr(conn,'virtual_pos',False):
            from sherif_local_identity import authorized_branch
            if owner['role']!='Super_Admin' or authorized_branch(conn,owner['id'])['branch_id']!=int(b_id):raise PermissionError('تغير سياق البيع؛ أعد فتح شاشة POS')

        # ====================================================
        # رصد البيع الاستثنائي دون إيقاف البيع أو تنبيه الكاشير
        # لا تُسجل التسوية تلقائياً؛ يراجعها المسؤول في لوحة التحكم.
        # ====================================================
        _draft_scope, _checkout_draft = _claim_cashier_draft(conn, b_id)
        if _checkout_draft['state'] == 'completed':
            conn.rollback()
            st.session_state['last_invoice'] = _checkout_draft.get('print_data')
            st.session_state['cart'] = []
            st.session_state['_sale_draft_record'] = None
            st.session_state['pos_success_pending'] = True
            st.session_state['pos_success_message'] = 'الفاتورة محفوظة بالفعل؛ لم يتم إنشاء بيع جديد.'
            st.rerun()
        ensure_inventory_batches_table(conn)
        stock_exceptions = []
        requested_by_item = {}
        for cart_item in st.session_state["cart"]:
            if cart_item.get("id") == 99999:
                continue
            item_id = int(cart_item["id"])
            requested_by_item[item_id] = requested_by_item.get(item_id, 0.0) + float(cart_item["qty"])
        for item_id, requested_qty in requested_by_item.items():
            stock_row = conn.execute(
                "SELECT id, item_name, quantity FROM items WHERE id=? AND branch_id=? FOR UPDATE",
                (item_id, b_id)
            ).fetchone()
            if not stock_row:
                raise ValueError("الصنف غير مسجل في الفرع المختار.")
            total_stock_qty = float(stock_row["quantity"] or 0)
            expired_tracked_qty = get_expired_tracked_quantity(conn, item_id, b_id)
            available_qty = max(0.0, total_stock_qty - expired_tracked_qty)
            if requested_qty > available_qty + 1e-8:
                stock_exceptions.append({
                    "item_id": item_id,
                    "item_name": stock_row["item_name"],
                    "requested_qty": requested_qty,
                    "available_qty": available_qty,
                    "shortfall_qty": round(requested_qty - available_qty, 6),
                    "branch_id": b_id,
                    "user_id": st.session_state.get("user_id", 1),
                    "recorded_at": datetime.now().isoformat(timespec="seconds"),
                })

        # ====================================================
        # بيانات الأصناف والخصم داخل notes
        # ====================================================

        from views.invoice_qr_image import selected_snapshot, company_name
        qr_asset_key, qr_image = selected_snapshot(conn)
        invoice_details = {
            "invoice_qr_asset": qr_asset_key,
            "_non_financial":bool(getattr(conn,"virtual_pos",False)),
            "_pos_policy_version":21,
            "items":
                st.session_state[
                    "cart"
                ].copy(),

            "gross_total":
                float(gross_total),

            "discount_type":
                discount_type,

            "discount_value":
                float(discount_value),

            "discount_amount":
                float(discount_amount),

            "final_total":
                float(final_tot),
            "stock_exceptions": stock_exceptions
        }

        if not getattr(conn,'virtual_pos',False):
            from branch_auth import local_device_info
            invoice_details['_source_device_number']=local_device_info().get('device_number')
        if selected_account_id and pay_method == "آجل (على الحساب)":
            invoice_details["customer_id"] = int(selected_account_id)
            invoice_details["account_statement"] = credit_balance_snapshot(conn, selected_account_id, final_tot)
        invoice_json = json.dumps(
            invoice_details,
            ensure_ascii=False
        )

        # الاسم النهائي المعتمد للفاتورة: العميل المسجل إن تم اختياره،
        # وإلا الاسم المدخل يدوياً، وإلا زبون نقدي.
        final_customer_name = str(cust_name or "").strip() or "زبون نقدي"
        final_customer_phone = str(cust_phone or "").strip()

        # ====================================================
        # حفظ/تحديث بيانات العميل عند إدخال الهاتف
        # ====================================================

        clean_phone = final_customer_phone
        clean_name = final_customer_name

        if clean_phone and not (selected_account_id and pay_method == "آجل (على الحساب)"):
            existing_customer = conn.execute(
                "SELECT id FROM customers WHERE phone = ? LIMIT 1",
                (clean_phone,)
            ).fetchone()

            if existing_customer:
                conn.execute(
                    """
                    UPDATE customers
                    SET customer_name = ?,
                        marketing_consent = ?
                    WHERE id = ?
                    """,
                    (
                        clean_name,
                        bool(marketing_consent),
                        existing_customer["id"]
                    )
                )
            else:
                conn.execute(
                    """
                    INSERT INTO customers
                    (customer_name, phone, total_purchases, balance, marketing_consent)
                    VALUES (?, ?, 0.0, 0.0, ?)
                    """,
                    (clean_name, clean_phone, bool(marketing_consent))
                )

        # ====================================================
        # حفظ الفاتورة - PostgreSQL
        # ====================================================

        invoice_row = conn.execute(
            """
            INSERT INTO invoices
            (
                branch_id,
                user_id,
                customer_name,
                customer_phone,
                total_amount,
                payment_method,
                notes,
                shift_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                b_id,
                st.session_state.get(
                    "user_id",
                    1
                ),
                final_customer_name,
                final_customer_phone,
                final_tot,
                pay_method,
                invoice_json,
                str(shift_num)
            )
        ).fetchone()

        inv_id = invoice_row["id"]
        from offline_store import claim_windows_invoice_number
        from sherif_local_identity import MODE_KEY, authorized_branch
        local_marker=conn.execute('SELECT 1 FROM local_meta WHERE key=?',(MODE_KEY,)).fetchone()
        if getattr(conn,'virtual_pos',False): reserved_number=conn.next_number()
        elif local_marker:
            binding=authorized_branch(conn,st.session_state.get('user_id'))
            generated=conn.execute('SELECT invoice_number,source_device_id FROM invoices WHERE id=?',(inv_id,)).fetchone()
            if binding['branch_id']!=int(b_id) or not generated or not generated['invoice_number'] or generated['source_device_id']!=binding['device_id']: raise ValueError('تعذر تأكيد رقم الفاتورة أو هوية الجهاز المحلي؛ لم يحفظ البيع.')
            reserved_number=generated['invoice_number']
        else: reserved_number=claim_windows_invoice_number(conn,b_id)
        conn.execute('UPDATE invoices SET invoice_number=? WHERE id=?',(reserved_number,inv_id))
        conn.execute('UPDATE invoices SET sold_at=? WHERE id=?', (datetime.now().astimezone().isoformat(timespec='seconds'),inv_id))
        invoice_number_row = conn.execute(
            "SELECT invoice_number FROM invoices WHERE id=?", (inv_id,)
        ).fetchone()
        invoice_number = invoice_number_row["invoice_number"] if invoice_number_row else None

        # سجل رقابي محلي لا يحتاج إلى صلاحية من الكاشير.
        # نقل التنبيه للسيرفر يتم مع نفس الفاتورة أثناء المزامنة.
        for exception in stock_exceptions:
            conn.execute(
                """INSERT INTO negative_sales_logs
                   (branch_id, user_id, item_name, sale_qty, log_time)
                   VALUES (?, ?, ?, ?, ?)""",
                (b_id, exception["user_id"], exception["item_name"],
                 exception["shortfall_qty"], exception["recorded_at"])
            )

        # ====================================================
        # خصم المخزون
        # ====================================================

        for cart_item in st.session_state["cart"]:

            if cart_item.get("id") == 99999:
                continue

            # خصم دفعات الصلاحية بالأقرب انتهاءً أولاً (FEFO).
            # إذا كان جزء من المخزون قديماً وغير مسجل كدفعات،
            # يبقى الخصم المتبقي محسوباً من رصيد items كالمعتاد.
            deduct_batches_fefo(
                conn,
                cart_item["id"],
                b_id,
                cart_item["qty"]
            )

            conn.execute(
                """
                UPDATE items
                SET quantity = quantity - ?
                WHERE id = ?
                  AND branch_id = ?
                """,
                (
                    cart_item["qty"],
                    cart_item["id"],
                    b_id
                )
            )

        # ====================================================
        # البيع الآجل
        # ====================================================

        if (
            selected_account_id
            and pay_method
            == "آجل (على الحساب)"
        ):

            conn.execute(
                """
                UPDATE customers
                SET
                    balance =
                        COALESCE(balance, 0) + ?,

                    total_purchases =
                        COALESCE(total_purchases, 0) + ?

                WHERE id = ?
                """,
                (
                    final_tot,
                    final_tot,
                    selected_account_id
                )
            )

        _draft_print_data = {
            "invoice_qr_image": qr_image,
            "company_name": company_name(conn),
            "_non_financial":bool(getattr(conn,"virtual_pos",False)),
            "inv_id":
                inv_id,

            "daily_inv_num":
                daily_inv_num,

            "invoice_number": invoice_number,

            "branch":
                branch_name_str,

            "cashier":
                cashier_name_str,

            "shift":
                shift_num,

            "date_time":
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),

            "customer":
                final_customer_name,

            "items":
                st.session_state[
                    "cart"
                ].copy(),

            "gross_total":
                float(gross_total),

            "discount_type":
                discount_type,

            "discount_value":
                float(discount_value),

            "discount_amount":
                float(discount_amount),

            "total":
                float(final_tot),

            "method":
                pay_method,
            "account_statement": invoice_details.get("account_statement")
        }
        if not getattr(conn,'virtual_pos',False):
            from offline_store import complete_sale_draft
            complete_sale_draft(conn, _draft_scope, _checkout_draft, inv_id, _draft_print_data)
        conn.commit()
        st.session_state['_sale_draft_record'] = None
        if not getattr(conn,'virtual_pos',False):_request_background_sync('invoice_saved')

        # ====================================================
        # حفظ آخر فاتورة للطباعة
        # ====================================================

        st.session_state[
            "last_invoice"
        ] = _draft_print_data

        st.session_state["cart"] = []
        # الفاتورة محفوظة في last_invoice للعرض والطباعة.
        # تعاد الحقول إلى قيمها الافتراضية عند ضغط المستخدم على "موافق".
        st.session_state["pos_success_pending"] = True
        st.session_state["pos_success_message"] = (
            f"تم إصدار الفاتورة رقم #{inv_id} بنجاح."
        )
        st.rerun()

    except ValueError as e:

        if conn:
            conn.rollback()

        st.error(
            f"⚠️ {e}"
        )

    except Exception as e:

        if conn:
            conn.rollback()

        st.error(
            "❌ حدث خطأ أثناء إصدار الفاتورة."
        )

        show_operation_error(e, announce=False, context='views/pos.py:1462')

    finally:

        try:
            if conn:
                conn.close()
        finally:
            if _pos_priority_held:
                from offline_store import end_pos_priority
                end_pos_priority()


# ============================================================
# معالجة باركود الميزان
# ============================================================

def _request_background_sync(reason):
    try:
        from auto_sync import request_sync
        request_sync(reason)
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Could not schedule background sync')


def _pos_optional_rows(conn, query):
    """Only a missing optional table may fall back; preserve the caller transaction."""
    import sqlite3
    ddl=getattr(conn, '_conn', conn)
    ddl.execute('SAVEPOINT pos_optional_read')
    try:
        rows=conn.execute(query).fetchall()
    except Exception as exc:
        ddl.execute('ROLLBACK TO SAVEPOINT pos_optional_read')
        ddl.execute('RELEASE SAVEPOINT pos_optional_read')
        if getattr(exc, 'pgcode', None)=='42P01' or (isinstance(exc,sqlite3.OperationalError) and 'no such table:' in str(exc)):
            import logging
            logging.getLogger(__name__).warning('Optional POS table missing; read isolated at savepoint')
            return []
        raise
    ddl.execute('RELEASE SAVEPOINT pos_optional_read')
    return rows

def _scale_settings(conn):
    defaults = {
        "scale_enabled": "1", "scale_prefix": "90",
        "scale_item_start": "2", "scale_item_length": "5",
        "scale_value_start": "7", "scale_value_length": "5",
        "scale_value_mode": "price", "scale_divisor": "100",
    }
    rows = _pos_optional_rows(conn,
        "SELECT setting_key, setting_value FROM app_settings WHERE setting_key LIKE 'scale_%'")
    for row in rows:
        defaults[row["setting_key"]] = str(row["setting_value"] or "")
    return defaults


def _parse_scale_barcode(conn, code):
    cfg = _scale_settings(conn)
    if cfg.get("scale_enabled") != "1":
        return None
    prefix = cfg.get("scale_prefix", "")
    if prefix and not code.startswith(prefix):
        return None
    try:
        item_start = int(cfg.get("scale_item_start", 2))
        item_len = int(cfg.get("scale_item_length", 5))
        value_start = int(cfg.get("scale_value_start", 7))
        value_len = int(cfg.get("scale_value_length", 5))
        divisor = float(cfg.get("scale_divisor", 1000) or 1000)
        if divisor <= 0:
            raise ValueError("معامل قسمة باركود الميزان يجب أن يكون أكبر من صفر")
        required_len = max(item_start + item_len, value_start + value_len)
        if len(code) < required_len:
            raise ValueError("باركود الميزان أقصر من الصيغة المحددة في الإعدادات")
        item_code = code[item_start:item_start + item_len]
        raw_value = code[value_start:value_start + value_len]
        if not raw_value.isdigit():
            raise ValueError("جزء الوزن/السعر في باركود الميزان غير رقمي")
        return {
            "item_code": item_code,
            "value": float(raw_value) / divisor,
            "mode": cfg.get("scale_value_mode", "weight"),
        }
    except (TypeError, ValueError) as exc:
        raise ValueError(f"تعذر فك باركود الميزان: {exc}")


# ============================================================
# معالجة الباركود
# ============================================================

def process_barcode_scan():

    ensure_cart()

    code = st.session_state.get(
        "barcode_scan_input",
        ""
    ).strip()

    qty_to_add = float(
        st.session_state.get(
            "barcode_qty_input",
            1.0
        )
    )

    if not code:
        return

    b_id = _pos_branch()

    if not b_id:
        st.error(
            "⚠️ لم يتم تحديد الفرع."
        )
        return

    conn = None

    try:

        conn, _pos_mode = get_pos_connection(actor_id=st.session_state.get('user_id'))

        from views.item_barcodes import resolve_plain,resolve_scale,parse_scale
        cfg=_scale_settings(conn)
        # Exact manufacturer/primary/alias match wins only when unambiguous.
        item=resolve_plain(conn,b_id,code)
        if item is None and code.isascii() and code.isdigit() and len(code)<=18:
            item=conn.execute('SELECT * FROM items WHERE id=? AND branch_id=?', (int(code),b_id)).fetchone()
        try:scale_data=parse_scale(code,cfg)
        except ValueError:
            if item is None:raise
            scale_data=None
        if scale_data:
            scale_item=resolve_scale(conn,b_id,scale_data['item_code'],int(cfg.get('scale_item_length',5)))
            if item is not None:
                if scale_item is not None and int(scale_item['id'])!=int(item['id']):
                    raise ValueError('الباركود يطابق صنف مصنع وصنف ميزان مختلفين؛ يلزم تصحيح الربط قبل البيع')
                scale_data=None
            else:item=scale_item
        if scale_data:
            if item is None:raise ValueError('كود الميزان غير مربوط بصنف في هذا الفرع')
            from views.scale_prices import measurement
            measured_weight,scale_measurement=measurement(scale_data,item,cfg.get('scale_divisor',100))
            qty_to_add=float(measured_weight)
            if qty_to_add<=0:raise ValueError('كمية الميزان يجب أن تكون موجبة')

        if item:

            unit_price = float(
                item["sale_price"] or 0
            )

            # لو نفس الصنف موجود بالسلة
            # نزود كميته بدل سطر جديد
            existing_cart_item = None

            for cart_item in st.session_state["cart"]:

                if (
                    cart_item.get("id")
                    == item["id"]
                ):
                    existing_cart_item = (
                        cart_item
                    )
                    break

            if existing_cart_item:

                existing_cart_item["qty"] += (
                    float(qty_to_add)
                )

                existing_cart_item["total"] = (
                    existing_cart_item["qty"]
                    * existing_cart_item["price"]
                )

            else:

                st.session_state["cart"].append(
                    {
                        "id":
                            item["id"],

                        "code":
                            item["item_code"],

                        "name":
                            item["item_name"],
                        "scale_measurement": scale_measurement if scale_data else None,
                        "unit": item["unit"] if "unit" in item.keys() else "",
                        "description": item["description"] if "description" in item.keys() else "",

                        "price":
                            unit_price,

                        "qty":
                            float(qty_to_add),

                        "total":
                            (
                                unit_price
                                * float(qty_to_add)
                            )
                    }
                )

            _persist_sale_draft()
            # تنبيه إجباري فور إضافة الصنف للسلة، وليس في آخر نافذة الدفع.
            cart_total_qty = 0.0
            for _cart_item in st.session_state["cart"]:
                if _cart_item.get("id") == item["id"]:
                    cart_total_qty += float(_cart_item.get("qty", 0) or 0)

            _stock_expiry_alert = get_item_stock_expiry_alert(
                conn,
                item["id"],
                b_id,
                cart_total_qty,
                threshold=5.0
            )

            st.session_state[
                "barcode_qty_input"
            ] = 1.0

            if _stock_expiry_alert:
                st.session_state["pos_stock_alert"] = _stock_expiry_alert
                return

        else:

            conn.close()
            conn = None

            st.session_state["pos_missing_item"] = (code, b_id)

            return

    except Exception as e:

        st.error(
            "❌ حدث خطأ أثناء قراءة الباركود."
        )

        show_operation_error(e, announce=False, context='views/pos.py:1707')

    finally:

        if conn:
            conn.close()

        st.session_state["pos_focus_barcode"] = True
        st.session_state[
            "barcode_scan_input"
        ] = ""


# ============================================================
# قراءة notes القديمة والجديدة
# ============================================================

def parse_invoice_notes(notes, total_amount):

    default_result = {
        "items": [],
        "gross_total": float(
            total_amount or 0
        ),
        "discount_type": "بدون خصم",
        "discount_value": 0.0,
        "discount_amount": 0.0,
        "final_total": float(
            total_amount or 0
        )
    }

    if not notes:
        return default_result

    try:

        data = json.loads(notes)

        # النظام الجديد
        if isinstance(data, dict):

            result = default_result.copy()

            result.update(data)

            return result

        # الفواتير القديمة
        if isinstance(data, list):

            default_result[
                "items"
            ] = data

            return default_result

    except Exception:
        pass

    return default_result


# ============================================================
# أدوات تقارير الخصم والطباعة المباشرة
# ============================================================

def summarize_invoice_rows(rows):
    gross_total = 0.0
    discount_total = 0.0
    net_total = 0.0
    discounted_count = 0
    payment_totals = {
        "كاش (نقدي)": 0.0,
        "شبكة / بطاقة": 0.0,
        "تحويل مصرفي": 0.0,
        "دفع آخر": 0.0,
        "آجل (على الحساب)": 0.0
    }
    manual_item_lines = 0
    manual_item_qty = 0.0
    manual_item_total = 0.0
    exceptions = []

    for row in rows:
        net = float(row["total_amount"] or 0)
        details = parse_invoice_notes(row["notes"], net)
        gross = float(details.get("gross_total", net) or net)
        discount = float(details.get("discount_amount", 0) or 0)
        method = row.get("payment_method", "") if hasattr(row, "get") else row["payment_method"]

        gross_total += gross
        discount_total += discount
        net_total += net

        if method in payment_totals:
            payment_totals[method] += net

        # تضمين البيع الاستثنائي في تقارير الوردية والإغلاق اليومي.
        for ex in details.get("stock_exceptions", []) or []:
            if not isinstance(ex, dict):
                continue
            item_name = str(ex.get("item_name") or "صنف غير محدد")
            qty = float(ex.get("requested_qty") or 0)
            shortfall = float(ex.get("shortfall_qty") or 0)
            status = str(ex.get("review_status") or "بانتظار المراجعة")
            exceptions.append(
                f"بيع استثنائي: {item_name} | كمية {qty:.2f} | عجز {shortfall:.2f} | {status}"
            )

        if discount > 0:
            discounted_count += 1
            exceptions.append(f"خصم على فاتورة بقيمة {discount:,.2f} د.ل")

        for item in details.get("items", []) or []:
            source = item.get("entry_source", "")
            if source in ("manual_search", "free_item") or item.get("id") == 99999:
                manual_item_lines += 1
                manual_item_qty += float(item.get("qty", 0) or 0)
                manual_item_total += float(item.get("total", 0) or 0)
                label = "صنف حر بدون كود" if (source == "free_item" or item.get("id") == 99999) else "إضافة يدوية"
                exceptions.append(f"{label}: {item.get('name', '-')} × {float(item.get('qty', 0) or 0):,.2f}")

    return {
        "gross_total": gross_total,
        "discount_total": discount_total,
        "net_total": net_total,
        "discounted_count": discounted_count,
        "invoice_count": len(rows),
        "cash_total": payment_totals["كاش (نقدي)"],
        "card_total": payment_totals["شبكة / بطاقة"],
        "transfer_total": payment_totals["تحويل مصرفي"],
        "other_total": payment_totals["دفع آخر"],
        "credit_total": payment_totals["آجل (على الحساب)"],
        "manual_item_lines": manual_item_lines,
        "manual_item_qty": manual_item_qty,
        "manual_item_total": manual_item_total,
        "exceptions": exceptions
    }


def make_printable_html(body_html, title="طباعة"):
    return f"""
    <!doctype html>
    <html dir="rtl">
    <head>
        <meta charset="utf-8">
        <title>{title}</title>
        <style>
            @page {{ margin: 3mm; }}
            body {{
                font-family: Arial, sans-serif;
                direction: rtl;
                text-align: center;
                width: 100%;
                max-width: 72mm;
                margin: 0 auto;
                color: #000;
                background: #fff;
                font-size: 12px;
            }}
            table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
            th, td {{
                padding: 3px 1px;
                border-bottom: 1px dashed #999;
                text-align: right;
            }}
            .left {{ text-align: left; }}
            .no-print {{ margin: 10px 0; }}
            @media print {{ .no-print {{ display: none !important; }} }}
        </style>
    </head>
    <body>
        {body_html}
        <div class="no-print">
            <button onclick="window.print()" style="
                width:100%; padding:10px; font-size:16px;
                font-weight:bold; cursor:pointer;
            ">🖨️ طباعة الآن</button>
        </div>
    </body>
    </html>
    """


def build_invoice_print_html(inv):
    from views.invoice_qr_image import invoice_qr_html
    from html import escape
    items_html = "".join(
        [
            (
                "<tr>"
                f"<td>{i.get('name', '-')}</td>"
                f"<td>{float(i.get('qty', 0) or 0):g}</td>"
                f"<td>{float(i.get('price', 0) or 0):.2f}</td>"
                f"<td>{float(i.get('total', 0) or 0):.2f}</td>"
                "</tr>"
            )
            for i in inv.get("items", [])
        ]
    )

    discount_amount = float(inv.get("discount_amount", 0) or 0)
    gross_total = float(inv.get("gross_total", inv.get("total", 0)) or 0)
    total = float(inv.get("total", 0) or 0)

    discount_html = ""
    if discount_amount > 0:
        discount_html = f"""
        <p class="left">الإجمالي قبل الخصم: <b>{gross_total:,.2f} د.ل</b></p>
        <p class="left">الخصم: <b>{discount_amount:,.2f} د.ل</b></p>
        """

    body = f"""
        <h2>{escape(str(inv.get('company_name') or 'المنشأة'))}</h2>
        <p>فرع: {inv.get('branch', '-')}</p>
        <hr>
        <p style="text-align:right;">
            <b>رقم فاتورة اليوم:</b> #{inv.get('daily_inv_num', '-')}<br>
            <b>رقم الفاتورة:</b> {inv.get('invoice_number') or ('#' + str(inv.get('inv_id', '-')))}<br>
            <b>التاريخ:</b> {inv.get('date_time', '-')}<br>
            <b>الكاشير:</b> {inv.get('cashier', '-')}<br>
            <b>الوردية:</b> {inv.get('shift', '-')}<br>
            <b>الزبون:</b> {inv.get('customer', 'زبون نقدي')}<br>
            <b>طريقة الدفع:</b> {inv.get('method', '-')}
        </p>
        <hr>
        <table>
            <tr><th>الصنف</th><th>الكمية</th><th>السعر</th><th>المجموع</th></tr>
            {items_html}
        </table>
        <hr>
        {discount_html}
        <h3 class="left">الصافي: {total:,.2f} د.ل</h3>
        <p>شكراً لتسوقكم معنا 🥜</p>
        {invoice_qr_html(inv.get('invoice_qr_image'))}
    """
    from views.pos_policy import document_html
    return document_html(make_printable_html(body, f"Invoice {inv.get('inv_id', '')}"),inv)


def get_shift_user_sales(conn, invoice_rows):
    grouped = {}
    for row in invoice_rows:
        uid = row["user_id"]
        key = str(uid) if uid is not None else "unknown"
        grouped.setdefault(key, []).append(row)
    names = {}
    for u in _pos_optional_rows(conn, "SELECT id, username FROM users"):
        names[str(u["id"])] = str(u["username"])
    result = []
    for key, rows in grouped.items():
        subtotal = summarize_invoice_rows(rows)
        result.append({"name": names.get(key, f"مستخدم رقم {key}"), "count": subtotal["invoice_count"], "gross": subtotal["gross_total"], "discount": subtotal["discount_total"], "net": subtotal["net_total"]})
    return sorted(result, key=lambda x: (-x["net"], x["name"]))


def build_shift_report_html(
    report_title, branch_name, username, shift_num, summary,
    supplier_payments_total=0.0, user_sales=None
):
    from html import escape
    user_sales = user_sales or []
    user_rows_html = "".join(
        "<tr><td>" + escape(u["name"]) + "</td>"
        + f'<td>{u["count"]}</td><td>{u["gross"]:,.2f}</td>'
        + f'<td>{u["discount"]:,.2f}</td><td>{u["net"]:,.2f}</td></tr>'
        for u in user_sales
    )
    users_html = (
        '<h4>مبيعات المستخدمين خلال الوردية</h4><table>'
        '<thead><tr><th>المستخدم</th><th>الفواتير</th><th>قبل الخصم</th>'
        '<th>الخصومات</th><th>الصافي</th></tr></thead><tbody>'
        + user_rows_html + '</tbody></table>'
        if user_sales else '<p>لا توجد مبيعات مستخدمين لهذه الوردية.</p>'
    )
    exceptions = summary.get("exceptions", [])
    exceptions_html = (
        "<br>".join(f"• {x}" for x in exceptions)
        if exceptions else "لا توجد حركات استثنائية مسجلة."
    )

    body = f"""
        <h2>{__import__('views.company_brand',fromlist=['company_label']).company_label()}</h2>
        <p>فرع: {branch_name}</p>
        <hr>
        <h3>{report_title}</h3>
        <p style="text-align:right;">
            <b>التاريخ:</b> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}<br>
            <b>الكاشير:</b> {username}<br>
            <b>الوردية:</b> {shift_num}
        </p>
        <hr>
        <p class="left">عدد الفواتير: <b>{summary["invoice_count"]}</b></p>
        <p class="left">إجمالي قبل الخصم: <b>{summary["gross_total"]:,.2f} د.ل</b></p>
        <p class="left">إجمالي الخصومات: <b>{summary["discount_total"]:,.2f} د.ل</b></p>
        <p class="left">إجمالي النقدي: <b>{summary.get("cash_total", 0):,.2f} د.ل</b></p>
        <p class="left">إجمالي البطاقة: <b>{summary.get("card_total", 0):,.2f} د.ل</b></p>
        <p class="left">إجمالي التحويل: <b>{summary.get("transfer_total", 0):,.2f} د.ل</b></p>
        <p class="left">إجمالي طرق الدفع الأخرى: <b>{summary.get("other_total", 0):,.2f} د.ل</b></p>
        <p class="left">إجمالي الآجل: <b>{summary.get("credit_total", 0):,.2f} د.ل</b></p>
        <p class="left">المدفوع من حسابات الموردين: <b>{supplier_payments_total:,.2f} د.ل</b></p>
        <p class="left">الأصناف المضافة يدوياً: <b>{summary.get("manual_item_lines", 0)}</b> حركة /
            {summary.get("manual_item_total", 0):,.2f} د.ل</p>
        <h3 class="left">صافي المبيعات: {summary["net_total"]:,.2f} د.ل</h3>
        <hr>
        {users_html}
        <hr>
        <h4>⚠️ الحركات والاستثناءات أثناء الوردية</h4>
        <p style="text-align:right;">{exceptions_html}</p>
    """
    return make_printable_html(body, report_title)




def get_shift_supplier_payments_total(conn, branch_id, shift_num, report_date):
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM supplier_payments
        WHERE branch_id = ?
          AND DATE(created_at) = ?
          AND shift_number = ?
        """,
        (branch_id, report_date, int(shift_num))
    ).fetchone()
    return float(row["total"] or 0) if row else 0.0


def _ensure_shift_finance_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS shift_closures(
        id INTEGER PRIMARY KEY AUTOINCREMENT, branch_id INTEGER NOT NULL, shift_date TEXT NOT NULL, shift_number INTEGER NOT NULL,
        gross_sales REAL DEFAULT 0, net_sales REAL DEFAULT 0, cash_amount REAL DEFAULT 0, card_amount REAL DEFAULT 0,
        transfer_amount REAL DEFAULT 0, credit_amount REAL DEFAULT 0, other_amount REAL DEFAULT 0, status TEXT DEFAULT 'closed',
        closed_by INTEGER, closed_at TEXT DEFAULT CURRENT_TIMESTAMP, notes TEXT, UNIQUE(branch_id, shift_date, shift_number))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS treasuries(
        id INTEGER PRIMARY KEY AUTOINCREMENT, treasury_name TEXT NOT NULL UNIQUE, treasury_type TEXT NOT NULL DEFAULT 'branch',
        branch_id INTEGER, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS treasury_movements(
        id INTEGER PRIMARY KEY AUTOINCREMENT, treasury_id INTEGER NOT NULL, movement_type TEXT NOT NULL, amount REAL NOT NULL,
        voucher_no TEXT, description TEXT, user_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    closure_cols={r['name'] for r in conn.execute('PRAGMA table_info(shift_closures)').fetchall()}
    for col,typ in [('shift_uuid','TEXT'),('device_id','TEXT')]:
        if col not in closure_cols:conn.execute(f'ALTER TABLE shift_closures ADD COLUMN {col} {typ}')
    cols={r['name'] for r in conn.execute('PRAGMA table_info(treasury_movements)').fetchall()}
    for col,typ in [('branch_id','INTEGER'),('payment_method','TEXT'),('movement_date','TEXT'),('source_type','TEXT'),('source_ref','TEXT')]:
        if col not in cols: conn.execute(f'ALTER TABLE treasury_movements ADD COLUMN {col} {typ}')

def _post_shift_close_to_treasury(conn, branch_id, branch_name, shift_date, shift_num, summary, user_id):
    _ensure_shift_finance_schema(conn)
    existing=conn.execute('SELECT id FROM shift_closures WHERE branch_id=? AND shift_number=?',(branch_id,int(shift_num))).fetchone()
    if existing: return existing['id']
    cur=conn.execute("""INSERT INTO shift_closures(branch_id,shift_date,shift_number,gross_sales,net_sales,cash_amount,card_amount,transfer_amount,credit_amount,other_amount,closed_by,notes)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(branch_id,shift_date,int(shift_num),summary['gross_total'],summary['net_total'],summary['cash_total'],summary['card_total'],summary['transfer_total'],summary['credit_total'],summary['other_total'],user_id,'إغلاق وردية تلقائي'))
    closure_id=cur.lastrowid
    identity=conn.execute('SELECT shift_uuid,source_device_id FROM invoices WHERE branch_id=? AND local_shift_number=? AND shift_uuid IS NOT NULL LIMIT 1',(branch_id,int(shift_num))).fetchone()
    if identity:
        conn.execute('UPDATE shift_closures SET shift_uuid=?,device_id=? WHERE id=?',(identity['shift_uuid'],identity['source_device_id'],closure_id))
    conn.execute("INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)",('last_shift_number:'+str(branch_id),str(int(shift_num))))
    # كل الفروع ترحّل إلى خزينة مركزية واحدة في المخزن الرئيسي،
    # مع الاحتفاظ بالفرع المصدر داخل حركة الخزينة.
    tr=conn.execute("SELECT id FROM treasuries WHERE treasury_type='company' ORDER BY id LIMIT 1").fetchone()
    if tr:
        tid=tr['id']
        conn.execute("UPDATE treasuries SET treasury_name='الخزينة الرئيسية', branch_id=NULL, is_active=1 WHERE id=?",(tid,))
    else:
        cur=conn.execute("INSERT INTO treasuries(treasury_name,treasury_type,branch_id,is_active) VALUES('الخزينة الرئيسية','company',NULL,1)"); tid=cur.lastrowid
    conn.execute("UPDATE treasuries SET is_active=0 WHERE treasury_type='branch'")
    ref=f'SHIFT-{branch_id}-{shift_date}-{int(shift_num)}'
    for method,amount in [('كاش',summary['cash_total']),('بطاقة',summary['card_total']),('تحويل',summary['transfer_total']),('أخرى',summary['other_total'])]:
        if float(amount)>0:
            conn.execute("""INSERT INTO treasury_movements(treasury_id,movement_type,amount,voucher_no,description,user_id,branch_id,payment_method,movement_date,source_type,source_ref)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(tid,'ترحيل وردية',float(amount),ref,f'ترحيل وردية فرع {branch_name} - {shift_date} - وردية {shift_num}',user_id,branch_id,method,shift_date,'shift_close',str(closure_id)))
    return closure_id


# ============================================================
# أرشيف تقارير Z السابقة
# ============================================================

def get_z_archive_dates(conn, branch_id):
    return conn.execute(
        """
        SELECT
            DATE(created_at) AS z_date,
            COUNT(*) AS invoice_count,
            COALESCE(SUM(total_amount), 0) AS net_total
        FROM invoices
        WHERE branch_id = ?
          AND shift_status = 'Z_Closed'
        GROUP BY DATE(created_at)
        ORDER BY DATE(created_at) DESC
        LIMIT 180
        """,
        (branch_id,)
    ).fetchall()


def build_historical_z_html(
    conn,
    branch_id,
    branch_name,
    selected_date
):
    rows = conn.execute(
        """
        SELECT total_amount, notes, payment_method
        FROM invoices
        WHERE branch_id = ?
          AND DATE(created_at) = ?
          AND shift_status = 'Z_Closed'
        ORDER BY id ASC
        """,
        (branch_id, selected_date)
    ).fetchall()

    summary = summarize_invoice_rows(rows)

    body = f"""
        <h2>{__import__('views.company_brand',fromlist=['company_label']).company_label()}</h2>
        <p>فرع: {branch_name}</p>
        <hr>
        <h3>إغلاق وردية سابق</h3>
        <p style="text-align:right;">
            <b>تاريخ التقرير:</b> {selected_date}<br>
            <b>الحالة:</b> مغلق
        </p>
        <hr>
        <p class="left">عدد الفواتير: <b>{summary["invoice_count"]}</b></p>
        <p class="left">إجمالي قبل الخصم: <b>{summary["gross_total"]:,.2f} د.ل</b></p>
        <p class="left">إجمالي الخصومات: <b>{summary["discount_total"]:,.2f} د.ل</b></p>
        <p class="left">عدد فواتير الخصم: <b>{summary["discounted_count"]}</b></p>
        <h3 class="left">صافي المبيعات: {summary["net_total"]:,.2f} د.ل</h3>
    """
    return make_printable_html(
        body,
        f"Shift Close {branch_name} {selected_date}"
    ), summary


# ============================================================
# الصفحة الرئيسية
# ============================================================

def _invoice_display_number(full_number):
    """Short screen label only; never use it for storage, printing or sync."""
    import re
    value = str(full_number or '')
    match = re.fullmatch(r'(B\d+-D\d+-\d+)-[0-9a-fA-F]{32}', value)
    return match.group(1) if match else value


def show_page():
    if st.session_state.get('document_correction_mode')=='sale':
        from views.document_corrections_ui import show_page as show_corrections
        return show_corrections('sale')
    from views.pos_policy import clear_disposed_state
    clear_disposed_state(st.session_state)
    _validated_role()
    role = _pos_actor()['role']
    is_cashier = role == "Cashier"

    # الكاشير يعمل داخل نقطة البيع مباشرة بدون زر رجوع يشتته عن شاشة البيع.
    # بقية الأدوار تحتفظ بزر الرجوع المعتاد.
    # Toolbar rendered after page styles, beside sync and connection indicator.

    item_alerts(_pos_branch(), key="alerts_pos")

    # نجاح بيع جديد في الجلسة الحالية فقط؛ لا نسترجع معاينة من المسودة المحفوظة.
    if st.session_state.get("pos_success_pending"):
        _pos_success_dialog()
        st.stop()

    if st.session_state.get("pos_stock_alert"):
        stock_expiry_warning_dialog(st.session_state["pos_stock_alert"])
        st.stop()
    if st.session_state.get("pos_missing_item"):
        add_missing_item_dialog(*st.session_state["pos_missing_item"])
        st.stop()


    # تنبيه سري لأدوار الإدارة عند الدخول إلى نقطة البيع، بما في ذلك
    # الحالات التي يكون فيها المدير نفسه هو مُصدر الفاتورة.
    if role in ("Super_Admin", "Admin", "Manager") and _pos_server_reachable():
        try:
            alert_conn = get_db_connection()
            try:
                recent = alert_conn.execute(
                    "SELECT inv.id, inv.notes, br.branch_name FROM invoices inv LEFT JOIN branches br ON br.id=inv.branch_id ORDER BY inv.id DESC LIMIT 200"
                ).fetchall()
            finally:
                alert_conn.close()
            pending_sales = []
            for inv_row in recent:
                try:
                    inv_details = parse_invoice_notes(inv_row["notes"], 0)
                    for ex in inv_details.get("stock_exceptions", []) or []:
                        if isinstance(ex, dict) and not ex.get("review_status"):
                            pending_sales.append((inv_row["id"], dict(ex, _branch_name=inv_row["branch_name"] or "فرع غير محدد")))
                except (TypeError, ValueError, AttributeError):
                    continue
            alert_signature = tuple(sorted(
                (str(inv_id), str(ex.get("item_id")))
                for inv_id, ex in pending_sales
            ))
            if (pending_sales and
                    st.session_state.get("pos_exception_alert_seen") != alert_signature):
                st.session_state["pos_exception_alert_seen"] = alert_signature

                @st.dialog("تنبيه إداري — بيع استثنائي")
                def _pos_exception_manager_dialog():
                    st.warning(f"يوجد {len(pending_sales)} بند بيع استثنائي يحتاج مراجعة الإدارة.")
                    for inv_id, ex in pending_sales[:8]:
                        st.write(
                            f"فاتورة {inv_id} | الفرع: {ex['_branch_name']} | {ex.get('item_name', '-')} | "
                            f"العجز {float(ex.get('shortfall_qty') or 0):.2f}"
                        )
                    if st.button("اطلعت على التنبيه", key="pos_exception_alert_ack"):
                        st.rerun()

                _pos_exception_manager_dialog()
        except Exception:
            pass  # فشل التنبيه لا يعطل نقطة البيع.

    ensure_cart()

    # تحسين أداء: تجهيز مخطط إضافات POS مرة واحدة فقط لكل جلسة،
    # بدلاً من إرسال أوامر DDL إلى PostgreSQL/Supabase مع كل rerun في Streamlit.
    if is_cashier and not st.session_state.get("pos_schema_ready", False) and _pos_server_reachable():
        try:
            ensure_pos_extensions_schema()
            st.session_state["pos_schema_ready"] = True
        except Exception as e:
            st.error("❌ تعذر تجهيز إضافات نقطة البيع.")
            show_operation_error(e, announce=False, context='views/pos.py:2235')
            return

    st.markdown(
        """
        <style>

        /* Compact cashier layout; preserve the original three-column design. */
        /* Reserve space below the fixed toolbar in both Streamlit layouts. */
        [data-testid="stAppViewContainer"] [data-testid="stMainBlockContainer"],
        [data-testid="stAppViewContainer"] .block-container,
        .stMainBlockContainer {
            padding-top: 0.35rem !important;
            padding-bottom: 0.7rem !important;
        }
        [data-testid="stMain"],
        [data-testid="stAppViewContainer"] section.main {
            scroll-padding-top: 1.3rem;
        }
        [data-testid="stAlert"], .cashier-hero {
            scroll-margin-top: 1.3rem;
        }
        [data-testid="stAppViewContainer"] [data-testid="stVerticalBlock"] {
            gap: 0.55rem;
        }
        .cashier-hero {
            margin-top: 0 !important;
            margin-bottom: 4px !important;
            padding: 11px 16px !important;
        }
        .cashier-hero .title {font-size: 21px !important;}
        .cashier-hero .meta {font-size: 12px !important;}
        .customer-display {gap: 9px !important; margin-top: 8px !important;}
        .customer-display .cell {padding: 9px 8px !important;}
        .top-panel {margin-bottom: 0 !important;}
        [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"] hr {
            margin-top: 0.55rem !important;
            margin-bottom: 0.55rem !important;
        }
        [data-testid="stAppViewContainer"] [data-testid="stButton"] > button {
            min-height: 42px;
        }
        [data-testid="stAppViewContainer"] label,
        [data-testid="stAppViewContainer"] .stMarkdown p {
            direction: rtl;
            text-align: right;
        }

        .top-panel {
            background-color: #e2e8f0;
            padding: 12px;
            border-radius: 8px;
            border: 1px solid #cbd5e1;
            margin-bottom: 12px;
            direction: rtl;
            text-align: right;
        }

        .totals-panel {
            background-color: #0f172a;
            color: #ffffff !important;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
            font-size: 19px;
            border: 2px solid #334155;
            margin-top: 8px;
            direction: rtl;
        }

        .rtl-container {
            direction: rtl !important;
            text-align: right !important;
        }

        .cashier-hero {
            direction: rtl;
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: white;
            border-radius: 18px;
            padding: 14px 18px;
            margin: 4px 0 14px 0;
            box-shadow: 0 10px 28px rgba(15, 23, 42, .16);
        }
        .cashier-hero .title {font-size: 22px; font-weight: 900; margin-bottom: 4px;}
        .cashier-hero .meta {font-size: 13px; opacity: .86;}
        .cashier-summary-meta {
            display:flex; justify-content:space-between; align-items:center;
            flex-wrap:wrap; gap:8px; font-size:13px; font-weight:800;
        }
        .cashier-summary .customer-display {margin-top:8px;}
        .cashier-summary .cell {padding:9px 10px;}
        .cashier-summary .cell .value {font-size:19px;}
        .cashier-summary .cell.grand .value {font-size:23px;}
        .customer-display {
            direction: rtl;
            display: grid;
            grid-template-columns: 1.15fr .9fr .9fr 1.45fr;
            gap: 10px;
            align-items: stretch;
            margin-top: 10px;
        }
        .customer-display .cell {
            background: #ffffff;
            border: 1px solid #cbd5e1;
            border-radius: 14px;
            padding: 10px 12px;
            text-align: center;
            color: #0f172a;
            box-shadow: 0 4px 14px rgba(15,23,42,.06);
        }
        .customer-display .label {font-size: 12px; color:#64748b; font-weight:800;}
        .customer-display .value {font-size: 20px; font-weight: 950; margin-top:3px;}
        .customer-display .grand {background:#0f172a; color:#fff; border-color:#0f172a;}
        .customer-display .grand .label {color:#cbd5e1;}
        .customer-display .grand .value {font-size: 27px;}
        div[data-testid="stButton"] > button {
            border-radius: 14px;
            min-height: 46px;
            font-weight: 800;
        }
        div[data-testid="stTextInput"] input,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stSelectbox"] > div > div {
            border-radius: 12px !important;
        }

        /* POS action buttons: readable single-line text on dark red. */
        [data-testid="stMain"] div[data-testid="stButton"] > button {
            background-color: #a00010 !important;
            border-color: #8c0010 !important;
            color: #ffffff !important;
            font-weight: 800 !important;
            font-size: clamp(11px, 1.12vw, 16px) !important;
            white-space: nowrap !important;
            min-height: 52px !important;
            padding-inline: 6px !important;
        }
        [data-testid="stMain"] div[data-testid="stButton"] > button p,
        [data-testid="stMain"] div[data-testid="stButton"] > button span {
            color: #ffffff !important;
            white-space: nowrap !important;
            overflow: visible !important;
            font-size: inherit !important;
        }
        [data-testid="stMain"] div[data-testid="stButton"] > button:hover {
            background-color: #85000c !important;
            color: #ffffff !important;
        }

        /* Invoice abbreviation affects screen presentation only. */
        .cashier-summary .invoice-id {
            direction:ltr; unicode-bidi:isolate; white-space:nowrap;
            font-variant-numeric:tabular-nums;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Right-aligned compact toolbar. Avoid nested columns in ui_common.back_button:
    # that helper allocates only 11.5% of its parent width and clips the label.
    tool_space, tool_status, tool_back = st.columns([6.35, 0.4, 1.45], gap="small")
    with tool_back:
        if not is_cashier and st.button("⬅️ رجوع", key="back_pos", use_container_width=True):
            _hist = st.session_state.get("_nav_history", [])
            if _hist:
                _target = _hist.pop()
                st.session_state["_nav_history"] = _hist
                st.session_state["page"] = _target
            else:
                st.session_state["page"] = "🏠 الرئيسية واللوحة"
            st.rerun()
    with tool_status:
        # Cashier already has connection status in the sidebar.
        # Keep the original indicator for other roles only.
        if not is_cashier:
            try:
                _online = bool(_pos_server_reachable())
            except Exception:
                _online = False
            _color = "#16a34a" if _online else "#dc2626"
            st.markdown(
                f'<div title="حالة اتصال السيرفر" style="padding-top:10px;text-align:center">'
                f'<span style="display:inline-block;width:17px;height:17px;'
                f'border-radius:50%;background:{_color};"></span></div>',
                unsafe_allow_html=True,
            )

    if not is_cashier:
        st.markdown('<h2 class="rtl-container">🛒 نقطة البيع (POS)</h2>', unsafe_allow_html=True)

    username = st.session_state.get(
        "username",
        ""
    )

    user_branch_id = _pos_branch()

    current_shift_num = None

    conn = None

    try:

        conn, _pos_mode = get_pos_connection(actor_id=st.session_state.get('user_id'))

        # ====================================================
        # تحديد الفرع
        # ====================================================

        if not is_cashier:
            branches=conn.execute('SELECT id,branch_name FROM branches WHERE is_active=1 ORDER BY branch_name').fetchall()
            if not branches:st.error('لا توجد فروع متاحة لهذا الحساب');return
            labels={int(row['id']):str(row['branch_name']) for row in branches}
            b_id=st.selectbox('الفرع',list(labels),format_func=lambda value:labels[value],key='pos_branch_selection')
            branch_name_display=labels[b_id]
        else:
            from views.branch_shift_state import registered_pos_branch
            b_id,branch_name_display=registered_pos_branch(conn,st.session_state.get('user_id'))
            st.caption('فرع هذا الجهاز: '+branch_name_display)
            st.session_state['branch_id']=b_id
        st.session_state['_pos_branch_id']=b_id

        current_shift_num = get_current_shift_number(conn, b_id)
        if is_cashier:
            from views.branch_shift_state import sale_hold_reason
            shift_hold=sale_hold_reason(conn,b_id,current_shift_num)
            if shift_hold:
                st.error(shift_hold)
                st.caption('لا تُعد إصدار الفواتير ولا تغلق الوردية مرة أخرى؛ السلة والفواتير المعلقة تبقى محفوظة.')
                _watch_current_shift(b_id,current_shift_num)
                return
        _bind_sale_draft(conn, b_id)
        _watch_current_shift(b_id,current_shift_num)
        if st.session_state.get("_sale_draft_save_failed"):
            _persist_sale_draft()

        # ====================================================
        # إشعارات التزويد
        # ====================================================

        pending_logs = [] if getattr(conn,"virtual_pos",False) else conn.execute(
            """
            SELECT *
            FROM transfer_logs
            WHERE to_branch_id = ?
              AND status = 'بانتظار تأكيد الكاشير'
            ORDER BY id DESC
            """,
            (b_id,)
        ).fetchall()

        if pending_logs:

            st.success(
                f"📦 توجد بضاعة واردة إلى "
                f"({branch_name_display}) "
                "تحتاج تأكيد الاستلام."
            )

            for pt in pending_logs:

                with st.container(
                    border=True
                ):

                    st.write(
                        f"رقم الحركة: "
                        f"#{pt['id']}"
                    )

                    st.write(
                        f"التاريخ: "
                        f"{pt['transfer_date']}"
                    )

                    st.write(
                        pt["items_details"]
                    )

            if st.button(
                "✅ تأكيد استلام البضاعة",
                type="primary",
                use_container_width=True
            ):

                from offline_store import acknowledge_transfers
                try:
                    acknowledge_transfers([pt['id'] for pt in pending_logs], b_id, username)
                except Exception as e:
                    show_operation_error(e, announce=True, context='views/pos.py:2526')
                    st.stop()

                _request_background_sync('transfer_receipt')
                notify_success('تم حفظ تأكيد الاستلام محلياً؛ المزامنة تعمل في الخلفية.')
                st.rerun()

            st.stop()

        # ====================================================
        # رقم فاتورة اليوم
        # ====================================================

        today_date = (
            datetime.now().date()
        )

        branch_inv_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM invoices
            WHERE branch_id = ?
              AND DATE(created_at) = ?
            """,
            (
                b_id,
                today_date
            )
        ).fetchone()[0]

        daily_inv_num = (
            int(branch_inv_count or 0)
            + 1
        )

        # Preview the next branch invoice number. The database trigger assigns
        # the authoritative number when the invoice is actually saved.
        from offline_store import next_invoice_number
        next_invoice_number_display = conn.next_number() if getattr(conn,'virtual_pos',False) else next_invoice_number(conn,b_id)
        short_invoice_number_display = _invoice_display_number(next_invoice_number_display)


        # تقارير X و Z تم نقلها إلى زر "التقارير والإغلاق"
        # لتبقى شاشة البيع الرئيسية خفيفة وغير مزدحمة.

        # ====================================================
        # آخر فاتورة - عرض وطباعة مباشرة
        # ====================================================

        if st.session_state.get("last_invoice"):

            inv = st.session_state["last_invoice"]
            html_file_content = build_invoice_print_html(inv)
            show_invoice_a4(inv, key='a4_saved_2_'+str(inv['inv_id']))

            st.success("✅ تمت عملية الدفع بنجاح.")
            st.info(
                "🖨️ اضغط «طباعة الآن» داخل الفاتورة لفتح نافذة "
                "الطباعة مباشرة من المتصفح."
            )

            st.components.v1.html(
                html_file_content,
                height=620,
                scrolling=True
            )

            c_inv1, c_inv2 = st.columns(2)

            with c_inv1:
                st.download_button(
                    "📥 تحميل الفاتورة (HTML)",
                    data=html_file_content.encode("utf-8"),
                    file_name=f"Invoice_{inv['inv_id']}.html",
                    mime="text/html",
                    use_container_width=True
                )

            with c_inv2:
                if st.button(
                    "✖️ إخفاء الفاتورة ومتابعة البيع",
                    type="primary",
                    use_container_width=True
                ):
                    st.session_state["last_invoice"] = None
                    st.session_state["pos_active_view"] = "الكاشير السريع"
                    st.session_state["pos_focus_barcode"] = True
                    st.rerun()

        # ====================================================
        # مركز إجراءات الكاشير الحديث
        # ====================================================

        if "pos_active_view" not in st.session_state:
            st.session_state["pos_active_view"] = "الكاشير السريع"
            st.session_state["pos_focus_barcode"] = True
        if st.session_state.get("pos_active_view") == "الكاشير":
            st.session_state["pos_active_view"] = "الكاشير السريع"

        # ملخص الفاتورة الحي — يظهر أعلى الشاشة مثل Customer Display
        cart_summary_items = st.session_state.get("cart", [])
        cart_distinct_items = len(cart_summary_items)
        cart_total_qty = sum(float(item.get("qty", 0) or 0) for item in cart_summary_items)
        cart_total_value = sum(float(item.get("total", 0) or 0) for item in cart_summary_items)

        # Same cashier layout on Windows and Contabo: full-width summary,
        # followed by one horizontal row of four navigation buttons.
        st.markdown(
            "\n".join(line.strip() for line in f"""<div class="top-panel cashier-summary" style="text-align:center; border-radius:12px; padding:10px;">
            <div class="cashier-summary-meta">
                <span>🏪 {branch_name_display}</span>
                <span>🕒 الوردية رقم {current_shift_num} — 👤 {username}</span>
                <span class="invoice-preview">🧾 رقم الفاتورة المتوقع <bdi class="invoice-id" title="{next_invoice_number_display}">{short_invoice_number_display}</bdi></span>
            </div>
            <div class="customer-display">
                <div class="cell"><div class="label">🧾 رقم الفاتورة المتوقع</div><div class="value invoice-id" dir="ltr" title="{next_invoice_number_display}">{short_invoice_number_display}</div></div>
                <div class="cell"><div class="label">📦 أصناف السلة</div><div class="value">{cart_distinct_items}</div></div>
                <div class="cell"><div class="label">⚖️ إجمالي الكمية</div><div class="value">{cart_total_qty:,.3f}</div></div>
                <div class="cell grand"><div class="label">💰 إجمالي الفاتورة</div><div class="value">{cart_total_value:,.2f} د.ل</div></div>
            </div>
            </div>""".splitlines()),
            unsafe_allow_html=True,
        )


        # Display reports/closing only for users authorized to view or close a shift.
        # This is a UI visibility check; the existing server-side permission checks remain.
        _shift_privileged = role in (
            "Super_Admin", "Admin", "Manager", "Supervisor",
            "General_Supervisor", "Branch_Supervisor"
        )
        _shift_allowed = _shift_privileged
        if not _shift_allowed:
            try:
                _shift_allowed = bool(
                    has_scoped_permission(conn, st.session_state.get("user_id"), b_id, "shift_view")
                    or has_scoped_permission(conn, st.session_state.get("user_id"), b_id, "shift_close")
                )
            except Exception:
                _shift_allowed = False
        if st.session_state.get("pos_active_view") == "التقارير" and not _shift_allowed:
            st.session_state["pos_active_view"] = "الكاشير السريع"

        # Navigation stays available when opening archive, search or reports.
        if st.session_state["pos_active_view"] != "الكاشير السريع":
            nav_reports, nav_archive, nav_manual, nav_quick = st.columns(4, gap="small")
            with nav_quick:
                if st.button("🛒 البيع السريع", key="pos_nav_quick", use_container_width=True):
                    st.session_state["pos_active_view"] = "الكاشير السريع"
                    st.rerun()
            with nav_manual:
                if st.button("🔎 بحث / بيع يدوي", key="pos_nav_manual", use_container_width=True):
                    st.session_state["pos_active_view"] = "البحث اليدوي"
                    st.rerun()
            with nav_archive:
                if st.button("🗂️ الأرشيف والطباعة", key="pos_nav_archive", use_container_width=True):
                    st.session_state["pos_active_view"] = "الأرشيف"
                    st.rerun()
            with nav_reports:
                if _shift_allowed:
                    if st.button("📊 التقارير والإغلاق", key="pos_nav_reports", use_container_width=True):
                        st.session_state["pos_active_view"] = "التقارير"
                        st.rerun()

        # ====================================================
        # الكاشير السريع
        # ====================================================

        if (
            st.session_state[
                "pos_active_view"
            ]
            == "الكاشير السريع"
        ):

            # Windows POS: lower labels slightly below the summary cards.
            st.markdown("""
            <style>
            .st-key-barcode_qty_input, .st-key-barcode_scan_input {
                margin-top: 8px !important;
            }
            </style>
            """, unsafe_allow_html=True)
            # Image-matched cashier: navigation / central cart / controls.
            pos_left, pos_center, pos_right = st.columns([1.65, 4.6, 1.65], gap="small")
            with pos_left:
                st.markdown("<div style='padding-top:8px;font-weight:700'>⚙️ العمليات</div>", unsafe_allow_html=True)
                if st.button("🔎 بحث / بيع يدوي", key="pos_nav_manual", use_container_width=True):
                    st.session_state["pos_active_view"] = "البحث اليدوي"
                    st.rerun()
                if st.button("🗂️ الأرشيف والطباعة", key="pos_nav_archive", use_container_width=True):
                    st.session_state["pos_active_view"] = "الأرشيف"
                    st.rerun()
                if not is_cashier and st.button("🔄 مزامنة الآن", key="pos_sync_now", use_container_width=True):
                    _request_background_sync('manual')
                    st.info('تم طلب المزامنة في الخلفية؛ يمكنك متابعة العمل.')
                if _shift_allowed:
                    if st.button("📊 التقارير والإغلاق", key="pos_nav_reports", use_container_width=True):
                        st.session_state["pos_active_view"] = "التقارير"
                        st.rerun()
            with pos_right:
                st.markdown("<div style='padding-top:8px;font-weight:700'>💳 الدفع والتحكم</div>", unsafe_allow_html=True)
                if st.button(
                    "❌ تفريغ السلة بالكامل",
                    use_container_width=True
                ):

                    st.session_state[
                        "cart"
                    ] = []
                    _persist_sale_draft()

                    st.rerun()

            with pos_center:
                col_qty, col_bar = (
                    st.columns(
                        [1, 3]
                    )
                )

                with col_qty:

                    ui_field(st.number_input, "pos:2274", 
                        "الكمية (كجم/وحدة):",
                        min_value=0.01,
                        value=1.0,
                        step=0.5,
                        key="barcode_qty_input"
                    )

                with col_bar:

                    ui_field(st.text_input, "pos:2284", 
                        "🔍 مسح الباركود "
                        "الفوري (Enter):",
                        key="barcode_scan_input",
                        on_change=(
                            process_barcode_scan
                        )
                    )

                    focus_barcode()
                    _cashier_checkout_keyboard()

                st.markdown(
                    "### 🧾 محتويات "
                    "سلة المبيعات"
                )

                cart_items_list = (
                    st.session_state[
                        "cart"
                    ]
                )

                # الملخص ظاهر أعلى الشاشة بشكل دائم؛ لا نكرره هنا.
                total_cart_qty = cart_total_qty
                total_cart_val = cart_total_value

                st.markdown("---")

                if not cart_items_list:

                    st.info(
                        "السلة فارغة حالياً."
                    )

                else:

                    for index, cart_item in enumerate(
                        cart_items_list
                    ):

                        (
                            c_col1,
                            c_col2,
                            c_col3,
                            c_col4,
                            c_col5
                        ) = st.columns(
                            [2, 1, 1, 1, 0.6]
                        )

                        c_col1.write(
                            f"🏷️ "
                            f"{cart_item['name']}"
                        )

                        c_col2.write(
                            f"كمية: "
                            f"{cart_item['qty']}"
                        )

                        c_col3.write(
                            f"سعر: "
                            f"{cart_item['price']:.2f}"
                        )

                        c_col4.write(
                            f"إجمالي: "
                            f"{cart_item['total']:.2f}"
                        )

                        if c_col5.button(
                            "🗑️",
                            key=(
                                f"del_cart_"
                                f"{index}"
                            )
                        ):

                            st.session_state[
                                "cart"
                            ].pop(index)
                            _persist_sale_draft()

                            st.rerun()

                g_tot = total_cart_val


                if st.button(
                    "💰 دفع واعتماد الفاتورة",
                    use_container_width=True,
                    type="primary"
                ):

                    if st.session_state[
                        "cart"
                    ]:

                        checkout_payment_dialog(
                            b_id,
                            g_tot,
                            branch_name_display,
                            username,
                            current_shift_num,
                            daily_inv_num
                        )

                    else:

                        st.warning(
                            "السلة فارغة."
                        )


            with pos_left:
                if st.button(
                    "📱 إضافة بيانات العميل",
                    use_container_width=True,
                    key="pos_customer_data_btn"
                ):
                    st.session_state["pos_show_customer_data"] = not st.session_state.get(
                        "pos_show_customer_data", False
                    )

                if st.session_state.get("pos_show_customer_data", False):
                    cc1, cc2 = st.columns(2)
                    st.session_state["pos_customer_name"] = ui_field(cc1.text_input, "pos:2424", 
                        "اسم العميل (اختياري):",
                        value=st.session_state.get("pos_customer_name", ""),
                        key="pos_customer_name_input"
                    )
                    st.session_state["pos_customer_phone"] = ui_field(cc2.text_input, "pos:2429", 
                        "رقم هاتف العميل:",
                        value=st.session_state.get("pos_customer_phone", ""),
                        key="pos_customer_phone_input"
                    )
                    st.session_state["pos_marketing_consent"] = ui_field(st.checkbox, "pos:2434", 
                        "يوافق على استقبال العروض والرسائل التسويقية",
                        value=bool(st.session_state.get("pos_marketing_consent", False)),
                        key="pos_marketing_consent_input"
                    )
        # ====================================================
        # التقارير والإغلاق
        # ====================================================

        elif (
            st.session_state["pos_active_view"]
            == "التقارير"
        ):

            st.markdown("### 📊 التقارير والإغلاق المالي")

            actor_id = st.session_state.get("user_id")
            privileged = role in ("Super_Admin", "Admin", "Manager", "Supervisor", "General_Supervisor", "Branch_Supervisor")
            branch_options = conn.execute("SELECT id, branch_name FROM branches ORDER BY branch_name").fetchall()
            permitted = [b for b in branch_options if privileged or
                         has_scoped_permission(conn, actor_id, b["id"], "shift_view") or
                         has_scoped_permission(conn, actor_id, b["id"], "shift_close")]
            if not permitted:
                st.warning("🔒 لا توجد صلاحية لعرض تقارير الإغلاق.")
            else:
                branch_labels = {f"{b['branch_name']} (#{b['id']})": b for b in permitted}
                choices = list(branch_labels)
                default_choice = next((i for i, k in enumerate(choices)
                                       if branch_labels[k]["id"] == b_id), 0)
                report_branch = branch_labels[st.selectbox("فرع التقرير والإغلاق", choices,
                    index=default_choice, key="shift_report_branch")]
                report_b_id = report_branch["id"]
                report_shift_num = get_current_shift_number(conn, report_b_id)
                report_branch_name = report_branch["branch_name"]
                can_close = privileged or has_scoped_permission(conn, actor_id, report_b_id, "shift_close")
                # Central figures are read-only; local Z stays as the device audit record.
                from datetime import date as _z_date
                z_day = st.date_input("تاريخ إجمالي مبيعات الفرع", value=_z_date.today(), key="central_z_day")
                if st.button("🔄 عرض إجمالي الفرع من السيرفر", key="central_z_refresh", use_container_width=True):
                    try:
                        central_z = get_central_shift_summary(report_b_id, z_day.isoformat())
                        st.session_state['central_z_result'] = central_z
                    except Exception as exc:
                        st.session_state.pop('central_z_result', None)
                        st.warning("تعذر جلب الإجمالي المركزي. تقرير الجهاز المحلي متاح بدون إنترنت.")
                        st.caption(str(exc))
                central_z = get_cached_central_shift_summary(report_b_id, z_day.isoformat())
                if central_z and central_z.get('branch_id') == report_b_id and central_z.get('shift_date') == z_day.isoformat():
                    st.metric("آخر إجمالي مؤكد لمبيعات الفرع", f"{central_z['net_sales']:,.2f} د.ل")
                    st.caption(f"آخر تحديث من السيرفر: {central_z.get('cached_at', 'غير معروف')} — عند انقطاع الإنترنت قد لا يشمل المبيعات الجديدة.")
                    st.caption(f"عدد الورديات المغلقة: {central_z['shift_count']} | فواتير Z على السيرفر: {central_z['invoice_count']} | إجمالي الفواتير: {central_z['invoices_total']:,.2f} د.ل")
                    if abs(central_z['net_sales'] - central_z['invoices_total']) > 0.01:
                        st.warning("تنبيه: إجمالي الإغلاق لا يطابق مجموع فواتير Z على السيرفر. يلزم تسوية قبل اعتماد التقرير المالي.")
                st.caption("تقرير Z المحلي يخص هذا الجهاز؛ الإجمالي أعلاه يخص الفرع كله ولا ينقل فواتير أو يخصم مخزونًا.")

                report_action = ui_field(st.selectbox, "pos:2503", 
                    "اختر التقرير أو العملية:",
                    [
                        "📊 ملخص الوردية الحالية",
                        "🔒 إغلاق الوردية"
                    ],
                    key="pos_report_action"
                )

                if report_action == "📊 ملخص الوردية الحالية":

                    shift_invoice_rows = conn.execute(
                        """
                        SELECT total_amount, notes, payment_method, user_id
                        FROM invoices
                        WHERE branch_id = ?
                          AND shift_status = ?
                        ORDER BY id ASC
                        """,
                        (
                            report_b_id,
                            str(report_shift_num)
                        )
                    ).fetchall()

                    x_summary = summarize_invoice_rows(
                        shift_invoice_rows
                    )

                    x1, x2, x3 = st.columns(3)
                    x1.metric(
                        "صافي الوردية",
                        f"{x_summary['net_total']:,.2f} د.ل"
                    )
                    x2.metric(
                        "الخصومات",
                        f"{x_summary['discount_total']:,.2f} د.ل"
                    )
                    x3.metric(
                        "عدد الفواتير",
                        f"{x_summary['invoice_count']}"
                    )

                    supplier_payments_total = get_shift_supplier_payments_total(
                        conn, report_b_id, report_shift_num, today_date
                    )

                    x_html = build_shift_report_html(
                        "ملخص الوردية الحالية",
                        report_branch_name,
                        username,
                        report_shift_num,
                        x_summary,
                        supplier_payments_total,
                        get_shift_user_sales(conn, shift_invoice_rows)
                    )

                    st.components.v1.html(
                        x_html,
                        height=360,
                        scrolling=True
                    )

                else:

                    z_invoice_rows = conn.execute(
                        """
                        SELECT id, total_amount, notes, payment_method, user_id
                        FROM invoices
                        WHERE branch_id = ?
                          AND shift_status = ?
                        ORDER BY id ASC
                        """,
                        (report_b_id, str(report_shift_num))
                    ).fetchall()

                    z_summary = summarize_invoice_rows(
                        z_invoice_rows
                    )

                    z1, z2, z3 = st.columns(3)
                    z1.metric(
                        "صافي غير المغلق",
                        f"{z_summary['net_total']:,.2f} د.ل"
                    )
                    z2.metric(
                        "الخصومات",
                        f"{z_summary['discount_total']:,.2f} د.ل"
                    )
                    z3.metric(
                        "عدد الفواتير",
                        f"{z_summary['invoice_count']}"
                    )

                    supplier_payments_total = get_shift_supplier_payments_total(
                        conn, report_b_id, report_shift_num, today_date
                    )

                    z_html = build_shift_report_html(
                        "إغلاق الوردية",
                        report_branch_name,
                        username,
                        report_shift_num,
                        z_summary,
                        supplier_payments_total,
                        get_shift_user_sales(conn, z_invoice_rows)
                    )

                    st.components.v1.html(
                        z_html,
                        height=360,
                        scrolling=True
                    )

                    if not z_invoice_rows:
                        st.info(
                            "لا توجد فواتير غير مغلقة لهذه الوردية."
                        )
                    elif not can_close:
                        st.warning("لا توجد صلاحية لإغلاق وردية هذا الفرع.")
                    elif st.button(
                        "🔒 تنفيذ إغلاق الوردية",
                        type="primary",
                        use_container_width=True
                    ):
                        try:
                            st.session_state[
                                "last_z_report_html"
                            ] = z_html

                            if not (role in ("Super_Admin", "Admin", "Manager", "Supervisor", "General_Supervisor", "Branch_Supervisor") or
                                    has_scoped_permission(conn, actor_id, report_b_id, "shift_close")):
                                raise PermissionError("لا توجد صلاحية لإغلاق وردية هذا الفرع")
                            if _pos_actor()['role']=='Cashier' and st.session_state.get('cart'):raise ValueError('أكمل الفاتورة المفتوحة قبل إغلاق الوردية')
                            _ensure_shift_finance_schema(conn)
                            prior = conn.execute("SELECT id FROM shift_closures WHERE branch_id=? AND shift_number=?",
                                (report_b_id, int(report_shift_num))).fetchone()
                            if prior:
                                st.error("هذه الوردية مغلقة بالفعل؛ لن تُرحّل مرة أخرى.")
                                st.stop()
                            from views.shift_closing import prepare_close
                            prepare_close(conn,report_b_id,report_shift_num,z_invoice_rows,get_current_shift_number,actor_id)
                            conn.execute(
                                """
                                UPDATE invoices
                                SET shift_status = 'Z_Closed'
                                WHERE branch_id = ?
                                          AND shift_status = ?
                                """,
                                (report_b_id, str(report_shift_num))
                            )
                            _post_shift_close_to_treasury(
                                conn, report_b_id, report_branch_name, today_date, report_shift_num, z_summary,
                                st.session_state.get("user_id")
                            )
                            conn.commit()
                            _request_background_sync('shift_closed')
                            st.session_state['_logout_handler']()
                            notify_success(
                                "✅ تم إغلاق الوردية "
                                "وحفظها في الأرشيف وترحيل المقبوضات تلقائياً إلى خزينة الفرع."
                            )
                            st.rerun()

                        except Exception:
                            conn.rollback()
                            raise

        # ====================================================
        # البحث اليدوي
        # ====================================================

        elif (
            st.session_state[
                "pos_active_view"
            ]
            == "البحث اليدوي"
        ):

            st.markdown(
                "### ⚡ البحث اليدوي "
                "عن الأصناف"
            )

            if st.button(
                "🛒 الرجوع للسلة",
                key="pos_manual_return_cart",
                use_container_width=True,
            ):
                st.session_state["pos_active_view"] = "الكاشير السريع"
                st.rerun()

            all_items_db = conn.execute(
                """
                SELECT *
                FROM items
                WHERE branch_id = ?
                ORDER BY item_name ASC
                """,
                (b_id,)
            ).fetchall()

            if all_items_db:

                # الكاشير لا يرى رصيد المخزون؛ يظل التحقق من الكمية
                # والخصم من المخزون يعملان في الخلفية عند اعتماد الفاتورة.
                hide_stock_quantity = role not in [
                    "Super_Admin", "Admin",
                    "General_Supervisor",
                    "Branch_Supervisor"
                ]

                # سعر التكلفة يظهر فقط للإدارة/المشرفين، ولا يظهر للكاشير.
                can_view_cost = role in [
                    "Super_Admin", "Admin",
                    "General_Supervisor",
                    "Branch_Supervisor"
                ]

                if hide_stock_quantity:
                    item_names_dict = {
                        (
                            f"{it['item_name']} "
                            f"(الكود: {it['item_code']} "
                            f"- السعر: "
                            f"{float(it['sale_price'] or 0):,.2f} د.ل)"
                        ): it
                        for it in all_items_db
                    }
                elif can_view_cost:
                    item_names_dict = {
                        (
                            f"{it['item_name']} "
                            f"(الكود: {it['item_code']} "
                            f"- سعر البيع: "
                            f"{float(it['sale_price'] or 0):,.2f} د.ل "
                            f"- التكلفة: "
                            f"{float(it['avg_cost'] or it['buy_price'] or 0):,.2f} د.ل "
                            f"- المتاح: "
                            f"{float(it['quantity'] or 0):,.2f})"
                        ): it
                        for it in all_items_db
                    }
                else:
                    item_names_dict = {
                        (
                            f"{it['item_name']} "
                            f"(الكود: {it['item_code']} "
                            f"- السعر: "
                            f"{float(it['sale_price'] or 0):,.2f} د.ل "
                            f"- المتاح: "
                            f"{float(it['quantity'] or 0):,.2f})"
                        ): it
                        for it in all_items_db
                    }

                selected_manual_item_str = (
                    ui_field(st.selectbox, "pos:2738", 
                        "اختر الصنف يدوياً:",
                        list(
                            item_names_dict.keys()
                        )
                    )
                )

                selected_item_obj = (
                    item_names_dict[
                        selected_manual_item_str
                    ]
                )

                if can_view_cost:
                    selected_cost = float(
                        selected_item_obj["avg_cost"]
                        or selected_item_obj["buy_price"]
                        or 0
                    )
                    selected_sale = float(
                        selected_item_obj["sale_price"] or 0
                    )
                    cc1, cc2, cc3 = st.columns(3)
                    cc1.metric("سعر التكلفة", f"{selected_cost:,.2f} د.ل")
                    cc2.metric("سعر البيع", f"{selected_sale:,.2f} د.ل")
                    cc3.metric(
                        "الفرق للوحدة",
                        f"{(selected_sale - selected_cost):,.2f} د.ل"
                    )

                manual_qty = ui_field(st.number_input, "pos:2769", 
                    "الكمية المطلوبة:",
                    min_value=0.01,
                    value=1.0,
                    step=0.1
                )

                if st.button(
                    "➕ إضافة إلى "
                    "سلة المبيعات",
                    type="primary"
                ):

                    sale_price = float(
                        selected_item_obj[
                            "sale_price"
                        ] or 0
                    )

                    st.session_state[
                        "cart"
                    ].append(
                        {
                            "id":
                                selected_item_obj[
                                    "id"
                                ],

                            "name":
                                selected_item_obj[
                                    "item_name"
                                ],
                            "unit": selected_item_obj["unit"] if "unit" in selected_item_obj.keys() else "",
                            "description": selected_item_obj["description"] if "description" in selected_item_obj.keys() else "",

                            "code":
                                selected_item_obj[
                                    "item_code"
                                ],

                            "price":
                                sale_price,

                            "qty":
                                float(
                                    manual_qty
                                ),

                            "total":
                                (
                                    sale_price
                                    * float(
                                        manual_qty
                                    )
                                ),
                            "entry_source": "manual_search"
                        }
                    )

                    _persist_sale_draft()
                    notify_success(
                        "✅ تمت إضافة "
                        "الصنف للسلة."
                    )

                    st.session_state["pos_active_view"] = "الكاشير السريع"
                    st.rerun()

            else:

                st.info(
                    "لا توجد أصناف "
                    "في هذا الفرع."
                )

            st.markdown("---")

            st.markdown(
                "### 🛒 بيع صنف حر "
                "(بدون كود)"
            )

            col_f1, col_f2, col_f3 = (
                st.columns(3)
            )

            free_name = ui_field(col_f1.text_input, "pos:2851", 
                "اسم الصنف:",
                value="صنف عام / خدمة"
            )

            free_price = (
                ui_field(col_f2.number_input, "pos:2857", 
                    "السعر (د.ل):",
                    min_value=0.0,
                    step=1.0,
                    format="%.2f"
                )
            )

            free_qty = (
                ui_field(col_f3.number_input, "pos:2866", 
                    "الكمية:",
                    min_value=0.01,
                    value=1.0,
                    step=1.0
                )
            )

            if st.button(
                "➕ إضافة الصنف الحر "
                "للفاتورة"
            ):

                if free_price > 0:

                    st.session_state[
                        "cart"
                    ].append(
                        {
                            "id": 99999,
                            "name":
                                free_name.strip()
                                or "صنف عام / خدمة",
                            "code": "FREE",
                            "price":
                                float(
                                    free_price
                                ),
                            "qty":
                                float(
                                    free_qty
                                ),
                            "total":
                                (
                                    float(
                                        free_price
                                    )
                                    * float(
                                        free_qty
                                    )
                                ),
                            "entry_source": "free_item"
                        }
                    )

                    _persist_sale_draft()
                    notify_success(
                        "✅ تمت إضافة "
                        "الصنف الحر."
                    )

                    st.session_state["pos_active_view"] = "الكاشير السريع"
                    st.rerun()

                else:

                    st.warning(
                        "يرجى إدخال "
                        "سعر صحيح."
                    )

        # ====================================================
        # الأرشيف وإعادة الطباعة
        # ====================================================

        elif (
            st.session_state["pos_active_view"]
            == "الأرشيف"
        ):

            st.markdown("### 🗂️ الأرشيف وإعادة الطباعة")

            archive_action = ui_field(st.selectbox, "pos:2936", 
                "ماذا تريد عرض أو إعادة طباعته؟",
                [
                    "🧾 فاتورة مبيعات سابقة",
                    "📊 إغلاق وردية سابق",
                    "📦 سجل التزويد"
                ],
                key="pos_archive_action"
            )

            # ------------------------------------------------
            # فواتير المبيعات
            # ------------------------------------------------
            if archive_action == "🧾 فاتورة مبيعات سابقة":
                _history_row=conn.execute('SELECT value FROM local_meta WHERE key=?',('replacement_history:'+str(int(b_id)),)).fetchone()
                if _history_row:
                    _history=json.loads(_history_row[0])
                    with st.expander('فواتير الجهاز السابق المؤكدة قبل الاستبدال'):
                        st.caption('سجل مركزي محفوظ للقراءة، لا يُعاد إرساله كمبيعات الجهاز البديل. آخر100 فاتورة؛ التاريخ الكامل محفوظ على السيرفر.')
                        st.dataframe([{'رقم الفاتورة':i['invoice_number'],'التاريخ':i['created_at'],'الجهاز الأصلي':i['source_device_id'],'الإجمالي':i['total_amount'],'الوردية المسجلة':i['shift_status']} for i in _history['invoices']],hide_index=True,width='stretch')


                recent_invs = conn.execute(
                    """
                    SELECT
                        id, invoice_number, sync_status,
                        customer_name,
                        total_amount,
                        created_at
                    FROM invoices
                    WHERE branch_id = ?
                    ORDER BY id DESC
                    LIMIT 100
                    """,
                    (b_id,)
                ).fetchall()

                if not recent_invs:
                    st.info("📭 لا توجد فواتير مبيعات سابقة.")

                else:
                    inv_dict = {
                        (
                            f"فاتورة {r['invoice_number'] or chr(35)+str(r['id'])} | "
                            f"{r['customer_name']} | "
                            f"{float(r['total_amount'] or 0):,.2f} د.ل | "
                            f"{r['created_at']} | {'وصلت للسيرفر' if r['sync_status']=='synced' else 'محفوظة محلياً'}"
                        ): r["id"]
                        for r in recent_invs
                    }

                    sel_inv_str = ui_field(st.selectbox, "pos:2980", 
                        "اختر الفاتورة:",
                        ["-- اختر الفاتورة --"]
                        + list(inv_dict.keys()),
                        key="archive_invoice_select"
                    )

                    if sel_inv_str != "-- اختر الفاتورة --":

                        target_inv_id = inv_dict[sel_inv_str]

                        inv_data = conn.execute(
                            """
                            SELECT *
                            FROM invoices
                            WHERE id = ?
                              AND branch_id = ?
                            """,
                            (target_inv_id, b_id)
                        ).fetchone()

                        if inv_data:
                            details = parse_invoice_notes(
                                inv_data["notes"],
                                inv_data["total_amount"]
                            )

                            from views.invoice_qr_image import load_snapshot, company_name
                            archive_print_inv = {
                                "invoice_qr_image": load_snapshot(conn, details.get("invoice_qr_asset")),
                                "company_name": company_name(conn),
                                "inv_id": inv_data["id"],
                                "daily_inv_num": "-",
                                "branch": branch_name_display,
                                "cashier": "-",
                                "shift": inv_data["shift_status"],
                                "date_time": inv_data["created_at"],
                                "customer": inv_data["customer_name"],
                                "items": details["items"],
                                "gross_total": float(
                                    details.get(
                                        "gross_total",
                                        inv_data["total_amount"]
                                    ) or 0
                                ),
                                "discount_amount": float(
                                    details.get(
                                        "discount_amount",
                                        0
                                    ) or 0
                                ),
                                "total": float(
                                    inv_data["total_amount"] or 0
                                ),
                                "method": inv_data["payment_method"],
                                    "account_statement": details.get("account_statement")
                            }

                            show_invoice_a4(archive_print_inv, key='a4_archive_'+str(target_inv_id))

                            html_reprint_content = (
                                build_invoice_print_html(
                                    archive_print_inv
                                )
                            )

                            st.components.v1.html(
                                html_reprint_content,
                                height=620,
                                scrolling=True
                            )

                            st.download_button(
                                "📥 تحميل الفاتورة",
                                data=html_reprint_content.encode(
                                    "utf-8"
                                ),
                                file_name=(
                                    f"Invoice_Reprint_"
                                    f"{target_inv_id}.html"
                                ),
                                mime="text/html",
                                use_container_width=True
                            )

            # ------------------------------------------------
            # أرشيف Z
            # ------------------------------------------------
            elif archive_action == "📊 إغلاق وردية سابق":

                z_dates = get_z_archive_dates(
                    conn,
                    b_id
                )

                if not z_dates:
                    st.info(
                        "📭 لا توجد تقارير Z مغلقة "
                        "مسجلة لهذا الفرع."
                    )

                else:
                    z_options = {
                        (
                            f"{r['z_date']} | "
                            f"{int(r['invoice_count'] or 0)} فاتورة | "
                            f"{float(r['net_total'] or 0):,.2f} د.ل"
                        ): r["z_date"]
                        for r in z_dates
                    }

                    selected_z_label = ui_field(st.selectbox, "pos:3085", 
                        "اختر إغلاق الوردية السابق:",
                        ["-- اختر إغلاق وردية --"]
                        + list(z_options.keys()),
                        key="archive_z_select"
                    )

                    if selected_z_label != "-- اختر إغلاق وردية --":

                        selected_z_date = z_options[
                            selected_z_label
                        ]

                        historical_z_html, historical_summary = (
                            build_historical_z_html(
                                conn,
                                b_id,
                                branch_name_display,
                                selected_z_date
                            )
                        )

                        zc1, zc2, zc3 = st.columns(3)
                        zc1.metric(
                            "الصافي",
                            f"{historical_summary['net_total']:,.2f} د.ل"
                        )
                        zc2.metric(
                            "الخصومات",
                            f"{historical_summary['discount_total']:,.2f} د.ل"
                        )
                        zc3.metric(
                            "الفواتير",
                            historical_summary["invoice_count"]
                        )

                        # Read-only central summary for the same archived date.
                        # This is distinct from the local device's historical Z.
                        if st.button(
                            "🌐 عرض إجمالي فرع الجزيرة/الفرع من السيرفر لهذا التاريخ",
                            key=f"archive_central_summary_{b_id}_{selected_z_date}",
                            use_container_width=True,
                        ):
                            try:
                                st.session_state["archive_central_summary"] = (
                                    get_central_shift_summary(b_id, selected_z_date)
                                )
                            except Exception as exc:
                                st.session_state.pop("archive_central_summary", None)
                                show_operation_error(exc, announce=True, context='views/pos.py:3620')
                        _central = get_cached_central_shift_summary(b_id, selected_z_date)
                        if (_central and _central.get("branch_id") == b_id
                                and _central.get("shift_date") == selected_z_date):
                            st.markdown("#### آخر إجمالي مركزي محفوظ — نفس تاريخ الإغلاق")
                            st.caption(f"آخر تحديث: {_central.get('cached_at', 'غير معروف')} | عند انقطاع الإنترنت هذه آخر نسخة مؤكدة وليست إجماليًا مباشرًا.")
                            c1, c2, c3 = st.columns(3)
                            c1.metric("إجمالي الإغلاقات المركزي", f"{_central['net_sales']:,.2f} د.ل")
                            c2.metric("إجمالي فواتير Z المركزي", f"{_central['invoices_total']:,.2f} د.ل")
                            c3.metric("عدد فواتير Z المركزية", _central["invoice_count"])
                            st.caption("التقرير أدناه خاص بالجهاز المحلي فقط؛ الإجمالي المركزي معروض أعلاه ولا يعيد ترحيل المبيعات أو المخزون.")
                            if abs(_central['net_sales'] - _central['invoices_total']) > 0.01:
                                st.warning("هناك فرق بين إجمالي الإغلاقات وإجمالي فواتير Z على السيرفر؛ يلزم مراجعة التسوية قبل اعتماد الإجمالي.")

                        st.components.v1.html(
                            historical_z_html,
                            height=420,
                            scrolling=True
                        )

                        st.download_button(
                            "📥 تحميل تقرير إغلاق الوردية",
                            data=historical_z_html.encode("utf-8"),
                            file_name=(
                                f"Z_Report_{b_id}_"
                                f"{selected_z_date}.html"
                            ),
                            mime="text/html",
                            use_container_width=True
                        )

            # ------------------------------------------------
            # سجل التزويد
            # ------------------------------------------------
            else:

                branch_transfers = conn.execute(
                    """
                    SELECT
                        id,
                        items_details,
                        status,
                        transfer_date
                    FROM transfer_logs
                    WHERE to_branch_id = ?
                    ORDER BY id DESC
                    LIMIT 100
                    """,
                    (b_id,)
                ).fetchall()

                if not branch_transfers:
                    st.info(
                        "لا توجد حركات تزويد "
                        "مسجلة لهذا الفرع."
                    )

                else:
                    transfer_options = {
                        (
                            f"تزويد #{r['id']} | "
                            f"{r['transfer_date']} | "
                            f"{r['status']}"
                        ): r
                        for r in branch_transfers
                    }

                    selected_transfer_label = ui_field(st.selectbox, "pos:3174", 
                        "اختر حركة التزويد:",
                        ["-- اختر حركة التزويد --"]
                        + list(transfer_options.keys()),
                        key="archive_transfer_select"
                    )

                    if (
                        selected_transfer_label
                        != "-- اختر حركة التزويد --"
                    ):
                        transfer_row = transfer_options[
                            selected_transfer_label
                        ]

                        transfer_body = f"""
                            <h2>{__import__('views.company_brand',fromlist=['company_label']).company_label()}</h2>
                            <p>فرع: {branch_name_display}</p>
                            <hr>
                            <h3>إيصال تزويد #{transfer_row['id']}</h3>
                            <p style="text-align:right;">
                                <b>التاريخ:</b>
                                {transfer_row['transfer_date']}<br>
                                <b>الحالة:</b>
                                {transfer_row['status']}
                            </p>
                            <hr>
                            <div style="
                                white-space:pre-wrap;
                                text-align:right;
                            ">
                                {transfer_row['items_details']}
                            </div>
                        """

                        transfer_html = make_printable_html(
                            transfer_body,
                            f"Transfer {transfer_row['id']}"
                        )

                        st.components.v1.html(
                            transfer_html,
                            height=480,
                            scrolling=True
                        )

                        st.download_button(
                            "📥 تحميل إيصال التزويد",
                            data=transfer_html.encode("utf-8"),
                            file_name=(
                                f"Transfer_"
                                f"{transfer_row['id']}.html"
                            ),
                            mime="text/html",
                            use_container_width=True
                        )

    except Exception as e:

        st.error(
            "❌ حدث خطأ داخل شاشة "
            "نقطة البيع."
        )

        show_operation_error(e, announce=False, context='views/pos.py:3751')

    finally:

        if conn:
            conn.close()
