"""Durable operation acknowledgements and success-only input resets.

This module has no database/network dependencies and is shared by the server
Streamlit UI and the locally running Windows Streamlit UI.
"""
from contextlib import contextmanager
import hashlib
import streamlit as st


def _page():
    return st.session_state.get('page', '')


def ui_field(widget, field_id, *args, **kwargs):
    """Register input state, keeping existing keys and callbacks unchanged."""
    if kwargs.get('key') is None:
        label = str(args[0] if args else kwargs.get('label', ''))
        identity = (label, args[1:], {k: v for k, v in kwargs.items() if k not in ('key', 'on_change', 'args', 'kwargs')})
        suffix = hashlib.sha256(repr(identity).encode()).hexdigest()[:12]
        kwargs['key'] = '_entry_' + field_id + '_' + suffix
    key = kwargs['key']
    registry = dict(st.session_state.get('_entry_fields', {}))
    registry[key] = (_page(), st.session_state.get('_entry_form'),
                     getattr(widget, '__name__', ''))
    st.session_state['_entry_fields'] = registry
    return widget(*args, **kwargs)


@contextmanager
def ui_form(*args, **kwargs):
    # clear_on_submit clears even rejected input. Reset only after success.
    kwargs['clear_on_submit'] = False
    previous = st.session_state.get('_entry_form')
    st.session_state['_entry_form'] = str(args[0] if args else kwargs['key'])
    try:
        with st.form(*args, **kwargs):
            yield
    finally:
        st.session_state['_entry_form'] = previous


def ui_submit(*args, **kwargs):
    submitted = st.form_submit_button(*args, **kwargs)
    if submitted:
        st.session_state['_entry_submitted'] = (_page(), st.session_state.get('_entry_form'))
    return submitted


def _fields_for_reset(form_only=False):
    submitted = st.session_state.get('_entry_submitted')
    return [key for key, (page, form, kind) in st.session_state.get('_entry_fields', {}).items()
            if page == _page() and (not form_only or not submitted or submitted == (page, form))]


def reset_page_fields(keys=None):
    """Defer deletion until the next full run, before widgets are instantiated."""
    st.session_state['_entry_reset'] = list(keys if keys is not None else _fields_for_reset())
    st.session_state['pos_focus_barcode'] = True


def begin_ui_run():
    st.session_state['_back_rendered_this_run']=False
    registry = dict(st.session_state.get('_entry_fields', {}))
    for key, (_, _, kind) in registry.items():
        if kind not in ('file_uploader','data_editor') and key in st.session_state:
            st.session_state[key]=st.session_state[key]
    for key in st.session_state.pop('_entry_reset', []):
        st.session_state.pop(key, None)
        registry.pop(key, None)
    st.session_state['_entry_fields'] = registry
    st.session_state.pop('_entry_submitted', None)
    # Keep draft fields alive while a confirmation dialog temporarily hides them.
    # Uploaders/editors cannot be assigned through session_state.
    dialog_pending = any((key.endswith(('_pending_action', '_success_pending', '_success_info')) or key in ('_operation_success', 'pos_stock_alert', 'pos_missing_item', 'finance_undo_open')) and bool(value)
                         for key, value in st.session_state.items() if isinstance(key, str))
    if not dialog_pending:
        return
    for key, (page, form, kind) in registry.items():
        if page == _page() and kind not in ('file_uploader', 'data_editor') and key in st.session_state:
            st.session_state[key] = st.session_state[key]


def notify_success(message, *, reset=True):
    """Queue only after commit. The caller can finish cleanup before rerunning."""
    st.session_state['_operation_success'] = {
        'message': str(message),
        'keys': _fields_for_reset(form_only=True) if reset else [],
    }


@st.dialog('✅ تمت العملية بنجاح', dismissible=False)
def _operation_success_dialog():
    info = st.session_state['_operation_success']
    st.success(info['message'])
    if info.get('report'):
        st.download_button('📥 تحميل تقرير الصفوف المتخطاة', info['report'],
                           'تقرير_اخطاء_استيراد_الأصناف.xlsx',
                           'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if st.button('موافق', key='_operation_success_ok', type='primary', use_container_width=True):
        reset_page_fields(info['keys'])
        st.session_state.pop('_operation_success', None)
        st.rerun()


def show_pending_success():
    if st.session_state.get('_operation_success'):
        _operation_success_dialog()
        st.stop()


def focus_barcode():
    """Restore scanner focus when idle; never interrupt manual editing."""
    st.components.v1.html('<script>(() => {\n  const doc = window.parent.document;\n  const host = window.parent;\n  if (host.__abuzaidBarcodeFocus) host.__abuzaidBarcodeFocus();\n  let timer;\n  function restore() {\n    clearTimeout(timer);\n    timer = setTimeout(() => {\n      if (!doc.hasFocus() || doc.querySelector(\'[role="dialog"], [data-testid="stDialog"]\')) return;\n      const target = Array.from(doc.querySelectorAll(\'input\')).find(el =>\n        (el.getAttribute(\'aria-label\') || \'\').includes(\'مسح الباركود\') &&\n        !el.disabled && el.getClientRects().length);\n      if (!target) return;\n      const active = doc.activeElement;\n      // Respect manual entry, selectors, editable tables and open popovers.\n      if (active && active !== target && active !== doc.body &&\n          (active.matches(\'input, textarea, select, [role="combobox"], [role="spinbutton"], [role="textbox"], [contenteditable="true"]\') ||\n           active.closest(\'[contenteditable="true"], [role="listbox"], [data-testid="stDataFrame"]\'))) return;\n      if (doc.querySelector(\'[role="listbox"], [role="menu"]\')) return;\n      if (active !== target) target.focus({preventScroll: true});\n    }, 120);\n  }\n  const observer = new MutationObserver(restore);\n  observer.observe(doc.body, {childList: true, subtree: true});\n  doc.addEventListener(\'focusout\', restore);\n  doc.addEventListener(\'click\', restore);\n  host.addEventListener(\'focus\', restore);\n  host.__abuzaidBarcodeFocus = () => {\n    clearTimeout(timer); observer.disconnect();\n    doc.removeEventListener(\'focusout\', restore);\n    doc.removeEventListener(\'click\', restore);\n    host.removeEventListener(\'focus\', restore);\n  };\n  restore();\n})();\n</script>', height=0, width=0)
