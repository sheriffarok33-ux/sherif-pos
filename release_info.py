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

def installed_source_release(root):
    """Read a source deployment's declared component without weakening validation."""
    path=Path(root)/'APP_VERSION.json'
    if not path.is_file():raise ValueError('Installed release metadata is missing')
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    component=value.get('component')
    if component not in ('windows','server'):raise ValueError('Invalid release component')
    return installed_release(root,component)

def display_update_number(value):
    return update_number(value)


def status_text(release,confirmed=False,state='',available=None):
    number=display_update_number(release)
    prefix='SHERIF POS | إصدار '+str(release['version'])+' | تحديث '+str(number)
    if confirmed:
        return prefix+' 🟢','البرنامج محدث'
    if state in ('install_failed','offline_or_rejected','blocked_release'):
        return prefix+' 🔴','تعذر التحديث'
    if state == 'downloading':
        message='جارٍ تنزيل التحديث'
    elif state in ('installing','restarting_for_update'):
        message='جارٍ تثبيت التحديث'
    elif state in ('ready_after_exit','shutdown_waiting_for_safe_exit'):
        message='التحديث جاهز بعد إغلاق البرنامج'
    elif state in ('trust_not_configured','device_required','outside_distribution',
                   'exe_requires_supervisor','helper_required','bootstrap_required'):
        message='التحديث غير مهيأ'
    elif type(available) is int and available>release['release_seq']:
        message='تحديث متاح'
    elif state == 'channel_behind':
        message='حالة التحديث غير متاحة'
    else:
        message='جارٍ التحقق من التحديث'
    return prefix+' 🟠',message


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
    except (OSError,ValueError,TypeError):label,message='SHERIF POS | 🔴','حالة الإصدار غير متاحة'
    color = '#15803d' if '🟢' in label else '#b91c1c' if '🔴' in label else '#b45309'
    st.markdown('<div style="position:fixed;bottom:10px;left:0;width:100%;text-align:center;font-size:16px;color:'+color+';font-weight:700;line-height:1.5;direction:rtl;pointer-events:none;z-index:25">'+html.escape(label)+'<br>'+html.escape(message)+'</div>',unsafe_allow_html=True)
