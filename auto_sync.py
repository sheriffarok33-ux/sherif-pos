"""One non-blocking sync worker. Only existing, valid user authorization is used.
Device-only renewal and historical reconciliation require an approved server contract.
"""
import logging
import threading
import time
import offline_store

_LOG = logging.getLogger(__name__)
_STOP = threading.Event()  # Pauses attempts; daemon is reused, never joined by UI.
_STOP.set()
_WAKE = threading.Event()
_THREAD = None
_LOCK = threading.Lock()
_PENDING = None
_INTERVAL_SECONDS = 30
_STATUS = {'running':False,'server_reachable':None,'last_attempt':None,
           'last_success':None,'state':'waiting_for_login','pending_invoices':None,
           'pending_operations':None}

def _diagnose(phase,error_type):
    # Reuse the existing signed updater reporter; no parallel sync worker.
    import sys
    callback=getattr(sys.modules.get('central_updater'),'record_sync_diagnostic',None)
    if callback:
        try:callback(phase,error_type)
        except Exception:pass


def _attempt_commands():
    try:
        from views.device_command_client import process_pending_command
        result=process_pending_command()
        with _LOCK:_STATUS['device_admin_command']=result
        return result
    except Exception as error:
        _diagnose('admin_command',type(error).__name__)
        with _LOCK:_STATUS['device_admin_command']={'state':'retry_pending','error_type':type(error).__name__}
        return {'state':'retry_pending'}


def _attempt_remote_shift_close():
    try:
        from views.remote_shift_close_client import process_pending_close
        result=process_pending_close()
        with _LOCK:_STATUS['remote_shift_close']=result
    except Exception as error:
        _diagnose('remote_shift_close',type(error).__name__)
        with _LOCK:_STATUS['remote_shift_close']={'state':'retry_pending','error_type':type(error).__name__}


def _attempt(token=None, refresh_users=False):
    with _LOCK:
        if _STOP.is_set():return
        _STATUS.update(state='checking',last_attempt=time.time())
    try:
        if _attempt_commands().get('state')=='completed':return
        from branch_auth import refresh_device_registration
        registration=refresh_device_registration()
        if registration.get('state')=='approval_required' or offline_store.device_registration_is_blocked():
            with _LOCK:_STATUS['state']='device_approval_required'
            return
        _attempt_remote_shift_close()
        with offline_store.sync_authorization(token):
            if not offline_store._current_api_token():
                with _LOCK:_STATUS.update(state='waiting_for_authorization',server_reachable=None)
                return
            reachable = offline_store.server_available()
            with _LOCK:_STATUS['server_reachable']=bool(reachable)
            if not reachable:
                with _LOCK:_STATUS['state']='offline'
                return
            try:heartbeat=offline_store.send_device_heartbeat()
            except Exception as exc:
                heartbeat={'state':'retry_pending','error_type':type(exc).__name__}
                _diagnose('device_heartbeat',type(exc).__name__)
            with _LOCK:_STATUS['device_heartbeat']=heartbeat
            try:
                reservation=offline_store.ensure_invoice_number_range()
                with _LOCK:_STATUS['invoice_number_range_ready']=bool(reservation.get('ready'))
            except Exception as exc:
                with _LOCK:_STATUS['invoice_number_range_ready']=False
                _diagnose('invoice_number_range',type(exc).__name__)
            if refresh_users:
                try:
                    users_ok, _ = offline_store.sync_offline_users()
                except Exception as exc:
                    users_ok=False
                    _diagnose('users_metadata',type(exc).__name__)
                    _LOG.exception('User metadata refresh failed; independent business sync continues')
                with _LOCK:_STATUS['users_ok']=bool(users_ok)
            result = offline_store.sync_now()  # Existing serialized/idempotent upload path.
            _attempt_remote_shift_close()
            if _attempt_commands().get('state')=='completed':return
            for stage,error_type in result.get('stage_errors',{}).items():
                _diagnose('sync_'+stage,str(error_type))
            if not result.get('auth_required') and result.get('download_ok'):
                for status_key, operation in (
                        ('historical_receipts',offline_store.reconcile_historical_invoice_receipts),
                        ('historical_erp_receipts',offline_store.reconcile_historical_erp_receipts),
                        ('historical_content',offline_store.reconcile_historical_content)):
                    try:value=operation()
                    except Exception as exc:
                        value={'state':'check_failed','needs_review':1,'error_type':type(exc).__name__}
                        _LOG.exception('Independent historical reconciliation failed: %s',status_key)
                    with _LOCK:_STATUS[status_key]=value

            complete = bool(result.get('download_ok')) and not any(result.get(k,0) for k in
                ('failed','ops_failed','shifts_failed','receipt_failed','settlements_failed'))
            with _LOCK:
                # A later empty page or throttled call cannot erase an earlier conflict.
                complete = complete and all(
                    not _STATUS.get(key,{}).get('needs_review',0)
                    and _STATUS.get(key,{}).get('state') not in ('check_failed','authorization_required','device_scope_unknown','device_branch_unknown')
                    for key in ('historical_receipts','historical_erp_receipts','historical_content'))
                complete = complete and bool(_STATUS.get('historical_content',{}).get('last_complete_match'))
                _STATUS['state']='up_to_date' if complete else 'needs_admin_review'
                if complete:_STATUS['last_success']=time.time()
    except Exception:
        with _LOCK:_STATUS['state']='retry_pending'
        _LOG.exception('Background sync failed; pending operations retained')
    finally:
        # Never expose credentials in status; counters are read by the worker only.
        try:
            invoices=offline_store.pending_count();operations=offline_store.pending_operations_count()
            with _LOCK:_STATUS.update(pending_invoices=invoices,pending_operations=operations)
        except Exception:pass

def _loop():
    global _PENDING
    offline_store.mark_background_sync_worker()
    while True:
        _WAKE.wait(_INTERVAL_SECONDS)
        with _LOCK:
            _WAKE.clear();pending=_PENDING;_PENDING=None
            paused=_STOP.is_set()
        if pending is not None:
            _attempt(pending[1], pending[2])
        elif not paused:
            _attempt()
        else:
            _attempt_commands()
            try:
                from views.invoice_cancellation_client import sync_cancellations
                result=sync_cancellations()
                with _LOCK:_STATUS['history_cancellations']=result
            except Exception as error:_diagnose('history_cancellations',type(error).__name__)

def _start_locked():
    global _THREAD
    if _THREAD is not None and _THREAD.is_alive():return False
    _THREAD=threading.Thread(target=_loop,name='abuzaid-background-sync',daemon=True)
    _THREAD.start();_STATUS['running']=True
    return True

def start_auto_sync():
    from sherif_network import server_enabled
    if not server_enabled(): return False
    with _LOCK:
        _STOP.clear();started=_start_locked();_WAKE.set()
    return started

def request_sync(reason='manual', token=None):
    """Coalesce wakeups. No database access, HTTP or thread join on the caller."""
    global _PENDING
    from sherif_network import server_enabled
    if not server_enabled(): return False
    with _LOCK:
        # A current-session request supersedes an old one-shot logout request.
        refresh_users = reason == 'admin_login' or bool(_PENDING and _PENDING[2] and reason != 'logout' and _PENDING[1] == token)
        _PENDING=(str(reason),token,refresh_users);_STOP.clear();_start_locked();_WAKE.set()
    return True

def stop_auto_sync():
    global _PENDING
    with _LOCK:
        _STOP.set();_PENDING=None;_STATUS.update(state='waiting_for_login',server_reachable=None)
    _WAKE.set()

def auto_sync_status():
    with _LOCK:return dict(_STATUS,interval_seconds=_INTERVAL_SECONDS,
                           running=bool(_THREAD and _THREAD.is_alive()))


def start_command_polling():
    # Keep the service available for explicit future server configuration.
    from sherif_network import server_enabled
    if not server_enabled(): return False
    with _LOCK:
        started=_start_locked();_WAKE.set();return started
