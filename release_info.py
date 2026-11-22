"""Unified public release numbers; internal replay counters are never reset."""
import json,re,hashlib
from pathlib import Path
VERSION_PATTERN=r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
BASE_VERSION='1.0.1'
NUMBERING_EPOCH=2
NUMBERING_BASE_SEQ=49

def update_number(value):
    sequence=value.get('release_seq')
    if type(sequence) is not int or sequence<0:raise ValueError('Invalid internal update sequence')
    return sequence-NUMBERING_BASE_SEQ+1 if sequence>=NUMBERING_BASE_SEQ else sequence

def release_metadata(value,component=None):
    component=component or value.get('component')
    if component not in ('windows','server') or not re.fullmatch(VERSION_PATTERN,str(value.get('version',''))):
        raise ValueError('Invalid release metadata')
    number=update_number(value);sequence=value['release_seq']
    epoch=NUMBERING_EPOCH if sequence>=NUMBERING_BASE_SEQ else 1
    if value.get('numbering_epoch',epoch)!=epoch or value.get('update_number',number)!=number:
        raise ValueError('Release numbering does not match its internal sequence')
    return {'version':value['version'],'release_seq':sequence,'component':component,
            'numbering_epoch':epoch,'update_number':number}

def installed_release(root,component):
    p=Path(root)/'APP_VERSION.json'
    if not p.is_file():raise ValueError('Installed release metadata is missing')
    value=json.loads(p.read_text(encoding='utf-8-sig'))
    if value.get('component')!=component:raise ValueError('Wrong installed component')
    return release_metadata(value,component)

def display_update_number(value):
    if value.get('release_seq') in (59,60,61,63,64,65,66,68):return 5
    return 4 if value.get('release_seq') in (53,54,55,56,58) else update_number(value)

def status_text(release,confirmed=False,state='',available=None):
    number=display_update_number(release)
    if confirmed:return 'SHERIF POS | تحديث '+str(number)+' 🟢','النظام محدّث وجاهز للعمل'
    if state in ('ready_after_exit','restarting_for_update','shutdown_waiting_for_safe_exit'):
        message='تحديث جديد جاهز؛ ينتظر انتهاء العمل المفتوح للتثبيت الآمن'
    elif type(available) is int and available>release['release_seq']:
        message='يوجد تحديث أحدث لم يُثبّت بعد'
    elif state in ('offline_or_rejected','channel_behind'):
        message='تعذر تأكيد آخر تحديث معتمد؛ العمل المحلي مستمر'
    else:message='جارٍ التحقق من تثبيت آخر تحديث معتمد'
    return 'SHERIF POS | تحديث '+str(number)+' ⚠️',message

def server_installation_confirmed(root,release):
    try:
        from central_updater import verify_envelope
        root=Path(root);keys=root/'update_public_keys.json'
        if not keys.is_file():keys=root.parents[1]/'keys/release_public_keys.json'
        manifest=verify_envelope(json.loads((root/'update_releases/latest-server.json').read_text()),json.loads(keys.read_text()))
        if manifest['release_seq']!=release['release_seq']:return False
        for row in manifest['files']:
            path=root/row['path']
            if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():return False
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:return False
        return True
    except (OSError,ValueError,KeyError,TypeError):return False

def release_badge(root,component,info=None):
    release=installed_release(root,component)
    if component=='server':return status_text(release,server_installation_confirmed(root,release))
    from central_updater import status,confirmed_current
    value=status() if info is None else info
    return status_text(release,confirmed_current(value,root),value.get('state',''),value.get('available_release_seq'))

def login_footer(root,component):
    import html
    import streamlit as st
    try:label,message=release_badge(root,component)
    except (OSError,ValueError,TypeError):label,message='SHERIF POS | ⚠️','تعذر التحقق من إصدار البرنامج'
    st.markdown('<div style="position:fixed;bottom:10px;left:0;width:100%;text-align:center;font-size:11px;color:#94a3b8;font-weight:400;line-height:1.4;direction:rtl;pointer-events:none;z-index:25">'+html.escape(label)+'<br>'+html.escape(message)+'</div>',unsafe_allow_html=True)
