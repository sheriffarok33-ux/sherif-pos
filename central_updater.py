"""SHERIF signed, data-preserving updater. Standard library only.
Trust anchor is provisioned offline; this module cannot update itself.
Signature: RSASSA-PKCS1-v1_5/SHA-256, RFC 8017, minimum RSA 3072 bits.
"""
import atexit
from contextlib import closing
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

ROOT = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
BASE_VERSION = "1.0.1"
UPDATER_PROTOCOL = 2
PRESTART_LOCK_PROTOCOL = 1
CORE = frozenset(("main.py offline_store.py database.py branch_auth.py auto_sync.py "
                 "backup_manager.py control_services.py https_invoice_sync.py "
                 "abuzaid_windows_dashboard.py central_inventory.py release_info.py central_updater.py update_audit.py").split())
MAX_PACKAGE = 384 * 1024 * 1024
MAX_FILE = 256 * 1024 * 1024
_APP_LOCK = None
_STARTED = False
_SCHEDULED = False
_STATUS = {"state": "waiting", "version": BASE_VERSION}
_THREAD_LOCK = threading.Lock()
_CHECK_LOCK = threading.RLock()
_DIAGNOSTIC_LOCK = threading.RLock()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def read_json(path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8-sig"))


def checked_path(root, relative):
    root = Path(root).resolve()
    parts = PurePosixPath(relative).parts
    if not parts or "\\" in relative or ":" in relative or relative.startswith("/") or any(p in (".", "..") for p in parts):
        raise ValueError("Unsafe update path")
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root):
        raise ValueError("Update path escapes application")
    current = root
    for part in parts:
        current = current / part
        if current.exists() or current.is_symlink():
            stat = current.lstat()
            if current.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise ValueError("Linked paths are forbidden")
    return target


def allowed_file(name, sherif_exe=False):
    if name in CORE or name == "AbuZaidPOS.exe" or (sherif_exe and name == "pos.exe"):
        return True
    return bool(re.fullmatch(r"views/[a-z][a-z0-9_]*\.py", name))


def version_info(root=ROOT):
    path=Path(root)/'APP_VERSION.json'
    if not path.is_file() and getattr(sys,'frozen',False) and Path(root).resolve()==ROOT.resolve():
        path=Path(getattr(sys,'_MEIPASS',str(root)))/'APP_VERSION.json'
    value=read_json(path)
    from release_info import release_metadata
    return release_metadata(value)


def verify_envelope(envelope, keys):
    payload = base64.b64decode(envelope["payload"], validate=True)
    signature = base64.b64decode(envelope["signature"], validate=True)
    if len(payload) > 256 * 1024:
        raise ValueError("Oversized manifest")
    key = keys[envelope["key_id"]]
    n = int(key["n"], 16)
    e = key["e"]
    if not 3072 <= n.bit_length() <= 8192 or e != 65537:
        raise ValueError("Unsupported signing key")
    size = (n.bit_length() + 7) // 8
    if len(signature) != size or int.from_bytes(signature, "big") >= n:
        raise ValueError("Invalid signature size")
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(payload).digest()
    expected = b"\x00\x01" + b"\xff" * (size - len(digest_info) - 3) + b"\x00" + digest_info
    actual = pow(int.from_bytes(signature, "big"), e, n).to_bytes(size, "big")
    if not hmac.compare_digest(expected, actual):
        raise ValueError("Untrusted update signature")
    return json.loads(payload)


def database_profile(root):
    profile=read_json(Path(root)/'.updates/database_format.json',{'format':1,'reader_min':1,'reader_max':1})
    if (any(type(profile.get(k)) is not int or profile[k]<1 for k in ('format','reader_min','reader_max'))
            or not profile['reader_min'] <= profile['format'] <= profile['reader_max']):
        raise ValueError('بيانات توافق قاعدة البيانات مش سليمة؛ التثبيت والرجوع اتوقفوا لحماية البيانات.')
    return profile


def compatibility_contract(manifest):
    contract=manifest.get('database_compatibility')
    if contract is None and {item.get('path') for item in manifest.get('files',[])} == {'release_info.py'}:
        # First signed pilot changes the footer only; no data reader is replaced.
        contract={'format':1,'reader_min':1,'reader_max':1,'schema_changes':False}
    if (not isinstance(contract,dict)
            or any(type(contract.get(k)) is not int or contract[k]<1 for k in ('format','reader_min','reader_max'))
            or not contract['reader_min'] <= contract['format'] <= contract['reader_max']
            or contract.get('schema_changes') is not False):
        raise ValueError('Automatic updates require an explicit unchanged-data compatibility contract')
    return contract


def assert_rollback_compatible(root,journal):
    from update_audit import database_snapshot
    profile=database_profile(root)
    previous=journal.get('previous_database_profile')
    schemas=journal.get('database_schemas')
    if not previous or not isinstance(schemas,dict):
        raise ValueError('الرجوع مرفوض: الإصدار السابق معهوش بيان توافق معتمد للبيانات الحالية.')
    if not previous['reader_min'] <= profile['format'] <= previous['reader_max']:
        raise ValueError('الرجوع مرفوض: الإصدار السابق مش بيدعم صيغة قاعدة البيانات الحالية.')
    for name,expected in schemas.items():
        path=checked_path(root,name)
        if not path.is_file() or database_snapshot(path)['schema_sha256'] != expected:
            raise ValueError('الرجوع مرفوض: هيكل قاعدة البيانات اتغيّر؛ مفيش استرجاع أو حذف للبيانات.')
    return profile


def validate_manifest(manifest, current, now=None, runtime=None, device_id=None, sherif_exe=False):
    now = time.time() if now is None else now
    if (manifest.get("protocol") != 1 or manifest.get("component") != "windows" or type(manifest.get("release_seq")) is not int
            or manifest["release_seq"] <= current["release_seq"]
            or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", manifest.get("version", ""))
            or manifest.get("requires_python") != (runtime or ".".join(map(str, sys.version_info[:2])))
            or manifest.get("platform") != "win_amd64"):
        raise ValueError("Incompatible or obsolete update")
    if (type(manifest.get("expires_at")) is not int or manifest["expires_at"] <= now
            or type(manifest.get("issued_at")) is not int or manifest["issued_at"] > now + 300
            or manifest["expires_at"] - manifest["issued_at"] > 90 * 86400):
        raise ValueError("Expired update")
    if (type(manifest.get("package_size")) is not int or not 0 < manifest["package_size"] <= MAX_PACKAGE
            or not re.fullmatch(r"[a-f0-9]{64}", manifest.get("package_sha256", ""))):
        raise ValueError("Invalid package identity")
    if manifest.get('min_updater_protocol',1)>UPDATER_PROTOCOL:
        raise ValueError('Updater bootstrap upgrade required')
    compatibility_contract(manifest)
    audience=manifest.get('audience')
    targets=manifest.get('target_device_ids')
    if (audience not in ('devices','all') or not isinstance(targets,list)
            or (audience == 'devices' and not targets) or (audience == 'all' and targets)
            or any(not isinstance(value,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',value) for value in targets)):
        raise ValueError('Update audience must be explicit')
    if device_id is not None and audience == 'devices' and device_id not in targets:
        raise ValueError('Update targets another device')
    files = manifest.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 300:
        raise ValueError("Invalid file inventory")
    names = set()
    for item in files:
        name = item.get("path", "")
        if (not allowed_file(name, sherif_exe=sherif_exe) or name.casefold() in names
                or type(item.get("size")) is not int or not 0 < item["size"] <= MAX_FILE
                or not re.fullmatch(r"[a-f0-9]{64}", item.get("sha256", ""))):
            raise ValueError("Forbidden file or invalid digest")
        names.add(name.casefold())
    if sum(item["size"] for item in files) > MAX_PACKAGE:
        raise ValueError("Expanded package too large")
    if manifest.get("kind") != ("exe" if names.intersection({"abuzaidpos.exe", "pos.exe"}) else "python"):
        raise ValueError("Package kind differs from contents")
    return manifest


def extract_verified(package, manifest, destination):
    expected = {item["path"]: item for item in manifest["files"]}
    with zipfile.ZipFile(package) as archive:
        entries = archive.infolist()
        if len(entries) != len(expected) or {e.filename for e in entries} != set(expected):
            raise ValueError("Package inventory differs from signed manifest")
        for entry in entries:
            item = expected[entry.filename]
            if not allowed_file(entry.filename):raise ValueError("Forbidden archive target")
            _STATUS["diagnostic_file"]=entry.filename
            if entry.file_size != item["size"] or entry.flag_bits & 1 or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Invalid archive entry")
            with archive.open(entry) as stream:
                content = stream.read(item["size"] + 1)
            if len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("File integrity check failed")
            if entry.filename.endswith(".py"):
                compile(content, entry.filename, "exec")
                if entry.filename == "main.py":
                    import ast
                    tree = ast.parse(content)
                    nodes = tree.body
                    if (len(nodes) < 2 or not isinstance(nodes[0], ast.ImportFrom)
                            or nodes[0].module != "central_updater"
                            or not isinstance(nodes[1], ast.Expr)
                            or not isinstance(nodes[1].value, ast.Call)
                            or not isinstance(nodes[1].value.func, ast.Name)
                            or nodes[1].value.func.id != "start_update_service"):
                        raise ValueError("Release omits early updater bootstrap")
            elif not content.startswith(b"MZ"):
                raise ValueError("Invalid Windows executable")
            path = checked_path(destination, entry.filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("Update redirects are forbidden")


class GitHubAssetRedirect(urllib.request.HTTPRedirectHandler):
    """Only allow HTTPS redirects to GitHub's release asset storage."""
    max_redirections=3
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit
        target=urlsplit(newurl)
        if (target.scheme!='https' or target.hostname not in
                ('release-assets.githubusercontent.com','objects.githubusercontent.com')
                or target.port not in (None,443) or target.username or target.password
                or target.fragment):
            raise ValueError('Untrusted GitHub asset redirect')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def fetch_github_asset(url, limit, destination=None):
    """Fetch public GitHub release asset over verified HTTPS with bounded redirects."""
    from urllib.parse import urlsplit
    parts=urlsplit(url)
    if (parts.scheme!='https' or parts.hostname!='github.com' or parts.port not in (None,443)
            or parts.username or parts.password or parts.query or parts.fragment
            or not re.fullmatch(r'/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/releases/download/[A-Za-z0-9_.-]+/(?:sherif-windows\.zip|sherif-windows-envelope\.json)',parts.path)):
        raise ValueError('Invalid GitHub release asset URL')
    request=urllib.request.Request(url,headers={'User-Agent':'SHERIF-updater'})
    with urllib.request.build_opener(GitHubAssetRedirect()).open(request,timeout=30) as response:
        if destination is None:
            data=response.read(limit+1)
            if len(data)>limit:raise ValueError('Oversized response')
            return data
        count=0
        with destination.open('wb') as stream:
            while True:
                chunk=response.read(min(128*1024,limit+1-count))
                if not chunk:break
                count+=len(chunk)
                if count>limit:raise ValueError('Oversized download')
                stream.write(chunk)
            stream.flush();os.fsync(stream.fileno())
        if count!=limit:raise OSError('Incomplete update download')
        return count


def api_base(root):
    from urllib.parse import urlsplit
    value = (Path(root) / "SERVER_URL.txt").read_text(encoding="utf-8-sig").strip().rstrip("/")
    url = urlsplit(value)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("HTTPS update server required")
    return value


def fetch(url, limit, destination=None, headers=None, body=None):
    import http.client
    opener=urllib.request.build_opener(NoRedirect())
    attempts=3 if destination is not None else 1
    for attempt in range(attempts):
        try:
            request=urllib.request.Request(url,data=body,headers=headers or {})
            with opener.open(request,timeout=30 if destination is not None else 8) as response:
                if destination is None:
                    value=response.read(limit+1)
                    if len(value)>limit:raise ValueError('Oversized response')
                    return value
                count=0
                with destination.open('wb') as stream:
                    while True:
                        chunk=response.read(min(128*1024,limit+1-count))
                        if not chunk:break
                        count+=len(chunk)
                        if count>limit:raise ValueError('Oversized download')
                        stream.write(chunk)
                    stream.flush();os.fsync(stream.fileno())
                if count!=limit:raise OSError('Incomplete update download')
                return count
        except urllib.error.HTTPError:
            raise
        except (OSError,http.client.IncompleteRead):
            if attempt+1==attempts:raise
            time.sleep(attempt+1)


def lock_file(path, timeout=30):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.monotonic() + timeout
    while True:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                raise TimeoutError("Application is still running")
            time.sleep(0.2)


def installed_pos_image_present(root, executable="AbuZaidPOS.exe"):
    """Read actual Windows image paths only; never terminate a process."""
    if os.name!='nt':return False
    import ctypes
    from ctypes import wintypes
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    p=ctypes.WinDLL('psapi',use_last_error=True)
    p.EnumProcesses.argtypes=[ctypes.POINTER(wintypes.DWORD),wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes=[wintypes.HANDLE]
    ids=(wintypes.DWORD*4096)();size=wintypes.DWORD()
    if not p.EnumProcesses(ids,ctypes.sizeof(ids),ctypes.byref(size)):raise ctypes.WinError(ctypes.get_last_error())
    expected=(Path(root)/executable).resolve()
    for pid in ids[:size.value//ctypes.sizeof(wintypes.DWORD)]:
        if not pid:continue
        handle=k.OpenProcess(0x1000,False,pid)
        if not handle:continue
        try:
            buffer=ctypes.create_unicode_buffer(32768);length=wintypes.DWORD(len(buffer))
            if k.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(length)) and Path(buffer.value).resolve()==expected:return True
        finally:k.CloseHandle(handle)
    return False


def assert_replaceable(path):
    """Check actual Windows sharing/readonly state; never terminate an owner."""
    if not path.exists():return
    if os.name!='nt':return
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,
        ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.GetFileAttributesW.argtypes=[wintypes.LPCWSTR]
    kernel.GetFileAttributesW.restype=wintypes.DWORD
    attributes=kernel.GetFileAttributesW(str(path))
    if attributes==0xffffffff:raise ctypes.WinError(ctypes.get_last_error())
    if attributes & 1:raise ctypes.WinError(5)  # Never remove protections to force an update.
    # A mapped executable may allow DELETE access yet reject os.replace. Test
    # write sharing too for image files, before changing ANY rollback target.
    # OPEN_EXISTING does not write bytes or remove attributes/ACLs.
    access=0x10000 | (0x40000000 if path.suffix.lower() in ('.exe','.dll','.pyd') else 0)
    handle=kernel.CreateFileW(str(path),access,0,None,3,0,None)
    if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    kernel.CloseHandle(handle)


def restore_files(root, journal, block_release=True):
    current_profile=assert_rollback_compatible(root,journal)
    from update_audit import snapshot,compare
    before=snapshot(root)
    # Authenticate every old byte against the previous signed inventory.
    envelope=journal.get('previous_runtime_envelope')
    if not envelope:raise ValueError('Signed rollback inventory is required')
    manifest=verify_envelope(envelope,read_json(root/'update_public_keys.json'))
    signed={item['path']:item for item in manifest['files']}
    plan=[]
    names=set()
    for item in journal['originals']:
        name=item['path']
        if not allowed_file(name) or name.casefold() in names:raise ValueError('Forbidden rollback target')
        names.add(name.casefold())
        target=checked_path(root,name)
        content=None
        if item['existed']:
            expected=signed.get(name)
            # Python-only releases authenticate compatible launcher images in
            # their signed host list rather than duplicating EXE in every ZIP.
            trusted_hosts=set(manifest.get('approved_worker_host_sha256',[]))
            trusted_hosts.add(manifest.get('installer_launcher_sha256'))
            trusted_exe=(name=='AbuZaidPOS.exe' and item['sha256'] in trusted_hosts)
            if (not expected and not trusted_exe) or (expected and expected['sha256']!=item['sha256']):
                raise ValueError('Unsigned rollback original')
            saved=checked_path(root/'.updates/rollback',str(journal['release_seq'])+'/'+name)
            content=saved.read_bytes()
            if (len(content)>MAX_FILE or (expected and len(content)!=expected['size'])
                    or hashlib.sha256(content).hexdigest()!=item['sha256']
                    or (trusted_exe and not content.startswith(b'MZ'))):
                raise ValueError('Rollback integrity failure')
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==item['sha256']:
                continue
        elif name in signed:
            raise ValueError('Rollback would delete a signed previous file')
        elif not target.exists():continue
        plan.append((name,target,content))
    # Refuse before any partial restore if a changed file is in use.
    for name,target,content in plan:
        _STATUS.update(phase='rollback_preflight',diagnostic_file=name)
        assert_replaceable(target)
    for name,target,content in plan:
        _STATUS.update(phase='rollback_replace',diagnostic_file=name)
        if content is None:target.unlink()
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            temp=target.with_name(target.name+'.update-tmp')
            with temp.open('wb') as stream:
                stream.write(content);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,target)
    if journal.get('previous_runtime_envelope'):
        atomic_json(root/'.updates/runtime-envelope.json',journal['previous_runtime_envelope'])
    elif 'previous_runtime_envelope' in journal:
        (root/'.updates/runtime-envelope.json').unlink(missing_ok=True)
    atomic_json(root / "APP_VERSION.json", journal["previous_version"])
    if block_release:
        atomic_json(root / '.updates/blocked.json',{'release_seq':journal['release_seq']})
    atomic_json(root / ".updates" / "result.json",
                {"state": "rolled_back", "release_seq": journal["release_seq"]})
    previous=journal['previous_database_profile']
    atomic_json(root/'.updates/database_format.json',dict(current_profile,reader_min=previous['reader_min'],reader_max=previous['reader_max']))
    audit_id='rollback-'+str(journal['release_seq'])+'-'+os.urandom(8).hex()
    audit_dir=checked_path(root,'.updates/audits/'+audit_id)
    after=snapshot(root)
    atomic_json(audit_dir/'before.json',before)
    atomic_json(audit_dir/'after.json',after)
    atomic_json(audit_dir/'comparison.json',compare(before,after))
    (root / ".updates" / "transaction.json").unlink(missing_ok=True)


def recover(root):
    path = root / ".updates" / "transaction.json"
    journal = read_json(path)
    if not journal:
        return
    if journal["state"] == "installing" or (journal["state"] == "trial" and journal.get("attempted")):
        try:restore_files(root, journal)
        except Exception as exc:
            _record_update_error(root,exc)
            # Keep the journal; an independent trusted host must finish recovery
            # before mixed code is allowed to run. Never restore a database.
            diagnostic=safe_diagnostic(_STATUS)
            atomic_json(root/'.updates/recovery-status.json',dict(diagnostic,state='recovery_required'))
            raise
    elif journal["state"] == "trial":
        journal["attempted"] = True
        atomic_json(path, journal)


def authorize_staged_scope(root,manifest,identity):
    try:
        active=verify_envelope(json.loads(fetch(api_base(root)+'/updates/latest?component=windows',524288,headers=identity['headers'])),read_json(root/'update_public_keys.json'))
        if active.get('release_seq')!=manifest['release_seq'] or active.get('package_sha256')!=manifest['package_sha256']:raise UpdateDeferred('distribution_changed')
    except (OSError,ValueError):raise UpdateDeferred('distribution_not_confirmed')



def install_staged(root):
    root = Path(root).resolve()
    # Caller owns app.lock after actual exit; code-only installation preserves
    # offline queues and saved drafts through the existing before/after audit.
    stage = checked_path(root, ".updates/staged")
    envelope = read_json(stage / "envelope.json")
    manifest = verify_envelope(envelope, read_json(root / "update_public_keys.json"))
    identity=device_identity(root)
    if not identity:
        raise ValueError('Existing approved device identity is required; never reinitialize for an update')
    validate_manifest(manifest, version_info(root), device_id=identity['device_id'])
    authorize_staged_scope(root,manifest,identity)
    profile=database_profile(root)
    contract=compatibility_contract(manifest)
    if contract['format'] != profile['format'] or not contract['reader_min'] <= profile['format'] <= contract['reader_max']:
        raise ValueError('التحديث مرفوض عشان توافق البيانات؛ مفيش تعديل في قاعدة البيانات.')
    package = stage / "package.zip"
    if package.stat().st_size != manifest["package_size"] or hashlib.sha256(package.read_bytes()).hexdigest() != manifest["package_sha256"]:
        raise ValueError("Package digest differs")
    verified = checked_path(root, ".updates/verified")
    verified.mkdir(parents=True, exist_ok=True)
    extract_verified(package, manifest, verified)
    # No code is changed while a onefile bootloader image is still finishing
    # cleanup. Actual sharing is checked; a stale PID/close certificate is not.
    deadline=time.monotonic()+30
    for item in manifest['files']:
        target=checked_path(root,item['path'])
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest()==item['sha256']:continue
        while True:
            try:assert_replaceable(target);break
            except OSError as exc:
                _STATUS.update(phase='install_file_preflight',diagnostic_file=item['path'])
                if (getattr(exc,'winerror',None) not in (5,32) or time.monotonic()>=deadline
                        or not installed_pos_image_present(root)):raise
                time.sleep(0.2)
    originals = []
    release = str(manifest["release_seq"])
    for item in manifest["files"]:
        name = item["path"]
        target = checked_path(root, name)
        original = {"path": name, "existed": target.exists()}
        if target.exists():
            content = target.read_bytes()
            original["sha256"] = hashlib.sha256(content).hexdigest()
            saved = checked_path(root, ".updates/rollback/" + release + "/" + name)
            saved.parent.mkdir(parents=True, exist_ok=True)
            with saved.open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        originals.append(original)
    journal = {"state": "installing", "release_seq": manifest["release_seq"],
               "previous_version": version_info(root), "originals": originals}
    # Durable journal is written before touching the first original program file.
    from update_audit import snapshot, compare
    audit_id='install-'+str(manifest['release_seq'])+'-'+os.urandom(8).hex()
    audit_dir=checked_path(root,'.updates/audits/'+audit_id)
    before=snapshot(root)
    journal['database_schemas']={name:data['schema_sha256'] for name,data in before['databases'].items()}
    journal['previous_database_profile']=profile
    journal['previous_runtime_envelope']=read_json(root/'.updates/runtime-envelope.json')
    journal['audit_id']=audit_id
    atomic_json(audit_dir/'before.json',before)
    data_check=None
    atomic_json(root / ".updates" / "transaction.json", journal)
    try:
        for item in manifest["files"]:
            target = checked_path(root, item["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            content = checked_path(verified, item["path"]).read_bytes()
            if hashlib.sha256(content).hexdigest() != item["sha256"]:
                raise ValueError("Staged file changed")
            temp = target.with_name(target.name + ".update-tmp")
            with temp.open("wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        after=snapshot(root)
        atomic_json(audit_dir/'after.json',after)
        data_check=compare(before,after)
        atomic_json(audit_dir/'comparison.json',data_check)
        if not data_check['unchanged']:
            raise ValueError('Protected data changed; restore program files only, never databases')
        if any(item['path']=='central_updater.py' for item in manifest['files']):
            atomic_json(root/'.updates/runtime-envelope.json',envelope)
        atomic_json(root / "APP_VERSION.json",
                    __import__('release_info').release_metadata(manifest,'windows'))
        atomic_json(root/'.updates/database_format.json',{'format':profile['format'],'reader_min':contract['reader_min'],'reader_max':contract['reader_max']})
        journal.update(state="trial", attempted=False)
        atomic_json(root / ".updates" / "transaction.json", journal)
        atomic_json(root / ".updates" / "result.json",
                    {"state": "awaiting_health", "release_seq": manifest["release_seq"]})
    except BaseException:
        restore_files(root, journal)
        if data_check is not None and not data_check['unchanged']:
            atomic_json(root / '.updates' / 'result.json',{'state':'data_check_failed','release_seq':manifest['release_seq']})
        raise


def _sherif_exe_item(manifest):
    files=manifest.get('files')
    if not isinstance(files,list) or len(files)!=1 or files[0].get('path')!='pos.exe':
        raise ValueError('SHERIF updates must contain pos.exe only')
    return files[0]


def _sherif_verified_original(root, journal, keys):
    previous=verify_envelope(journal['previous_envelope'],keys)
    item=_sherif_exe_item(previous)
    if item.get('sha256')!=journal['original_sha256']:
        raise ValueError('Rollback original is not signed')
    path=checked_path(root,'.updates/sherif/rollback/pos.exe')
    content=path.read_bytes()
    if len(content)!=item.get('size') or hashlib.sha256(content).hexdigest()!=item['sha256']:
        raise ValueError('Rollback original failed integrity verification')
    return content


def discover_sherif_github_release(owner, repository):
    """Discover explicit release assets; the caller must verify the signed envelope."""
    from urllib.parse import urlsplit
    if not isinstance(owner,str) or not isinstance(repository,str):
        raise ValueError('Invalid GitHub repository')
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?',owner):
        raise ValueError('Invalid GitHub repository')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',repository) or repository in ('.','..'):
        raise ValueError('Invalid GitHub repository')
    endpoint='https://api.github.com/repos/'+owner+'/'+repository+'/releases/latest'
    payload=fetch(endpoint,512*1024,headers={'Accept':'application/vnd.github+json','User-Agent':'SHERIF-updater'})
    release=json.loads(payload)
    if not isinstance(release,dict) or release.get('draft') is not False or release.get('prerelease') is not False:
        raise ValueError('Invalid GitHub release')
    tag=release.get('tag_name')
    if not isinstance(tag,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',tag) or tag in ('.','..'):
        raise ValueError('Invalid GitHub release tag')
    assets=release.get('assets')
    if not isinstance(assets,list):
        raise ValueError('Invalid GitHub release assets')
    expected={'sherif-windows-envelope.json','sherif-windows.zip'}
    found={}
    for asset in assets:
        if not isinstance(asset,dict) or asset.get('name') not in expected:
            continue
        name=asset['name']
        if name in found or not isinstance(asset.get('browser_download_url'),str):
            raise ValueError('Duplicate or invalid release asset')
        url=asset['browser_download_url']
        parts=urlsplit(url)
        path='/'+owner+'/'+repository+'/releases/download/'+tag+'/'+name
        if (parts.scheme!='https' or parts.hostname!='github.com' or parts.port not in (None,443)
                or parts.username or parts.password or parts.query or parts.fragment or parts.path!=path):
            raise ValueError('Release asset outside configured repository')
        found[name]=url
    if set(found)!=expected:
        raise ValueError('Required release assets missing')
    return {'tag':tag,'envelope_url':found['sherif-windows-envelope.json'],
            'package_url':found['sherif-windows.zip']}


def stage_sherif_candidate(root, envelope, previous_envelope, package_url, device_id=None):
    """Verify and stage a GitHub-hosted candidate; does not schedule or install it."""
    from urllib.parse import urlsplit
    root=Path(root).resolve()
    url=urlsplit(package_url)
    if (url.scheme != 'https' or url.hostname not in ('raw.githubusercontent.com','github.com')
            or url.username or url.password or url.port not in (None, 443)
            or url.query or url.fragment):
        raise ValueError('Invalid GitHub update package URL')
    stage=checked_path(root,'.updates/sherif')
    keys=read_json(checked_path(root,'update_public_keys.json'))
    candidate=verify_envelope(envelope,keys)
    previous=verify_envelope(previous_envelope,keys)
    if type(previous.get('release_seq')) is not int:
        raise ValueError('Signed previous release sequence is required')
    if candidate.get('audience') == 'devices' and not device_id:
        raise ValueError('Device identity required for targeted update')
    validate_manifest(candidate,{'release_seq':previous['release_seq']},device_id=device_id,sherif_exe=True)
    item=_sherif_exe_item(candidate)
    original=_sherif_exe_item(previous)
    if compatibility_contract(candidate)['format'] != compatibility_contract(previous)['format']:
        raise ValueError('Database format differs; update stopped')
    installed=checked_path(root,'pos.exe')
    if not installed.is_file() or installed.stat().st_size != original['size']:
        raise ValueError('Installed executable has no signed rollback identity')
    if hashlib.sha256(installed.read_bytes()).hexdigest() != original['sha256']:
        raise ValueError('Installed executable has no signed rollback identity')
    stage.mkdir(parents=True,exist_ok=True)
    lock=lock_file(checked_path(root,'.updates/sherif/worker.lock'),timeout=0)
    try:
        if (stage/'transaction.json').exists() or (stage/'request.json').exists():
            raise RuntimeError('Existing update transaction requires recovery')
        part=checked_path(root,'.updates/sherif/candidate.part')
        package=checked_path(root,'.updates/sherif/candidate.zip')
        try:
            count=(fetch_github_asset(package_url,candidate['package_size'],part) if url.hostname=='github.com'
                   else fetch(package_url,candidate['package_size'],part))
            if count != candidate['package_size'] or hashlib.sha256(part.read_bytes()).hexdigest()!=candidate['package_sha256']:
                raise ValueError('Package digest differs')
            with zipfile.ZipFile(part) as archive:
                entries=archive.infolist()
                if len(entries)!=1 or entries[0].filename!='pos.exe' or entries[0].flag_bits & 1 or entries[0].file_size!=item['size']:
                    raise ValueError('Invalid SHERIF package inventory')
                content=archive.read(entries[0])
            if len(content)!=item['size'] or not content.startswith(b'MZ') or hashlib.sha256(content).hexdigest()!=item['sha256']:
                raise ValueError('SHERIF executable integrity check failed')
            os.replace(part,package)
            atomic_json(stage/'request.json',{'envelope':envelope,'previous_envelope':previous_envelope})
        finally:
            part.unlink(missing_ok=True)
        return {'state':'staged','release_seq':candidate['release_seq']}
    finally:
        lock.close()


def discover_and_stage_sherif_release(root, owner, repository, device_id=None):
    """Discover a release and stage it after verification; never install automatically."""
    root=Path(root).resolve()
    previous=read_json(checked_path(root,'.updates/sherif/last-good-envelope.json'))
    if not previous:
        raise ValueError('Signed installed baseline is not configured')
    keys=read_json(checked_path(root,'update_public_keys.json'))
    if not keys:
        raise ValueError('Update trust is not configured')
    # Reject an untrusted baseline before contacting the release channel.
    verify_envelope(previous,keys)
    release=discover_sherif_github_release(owner,repository)
    envelope=json.loads(fetch_github_asset(release['envelope_url'],512*1024))
    return stage_sherif_candidate(root,envelope,previous,release['package_url'],device_id=device_id)


def _recover_sherif_update(root):
    """Offline rollback of a signed previous executable; never touch customer data."""
    root=Path(root).resolve();journal_path=checked_path(root,'.updates/sherif/transaction.json')
    if not journal_path.is_file():return False
    keys=read_json(checked_path(root,'update_public_keys.json'))
    journal=read_json(journal_path);content=_sherif_verified_original(root,journal,keys)
    if installed_pos_image_present(root,'pos.exe'):raise RuntimeError('SHERIF is still running')
    target=checked_path(root,'pos.exe');assert_replaceable(target)
    current_hash=hashlib.sha256(target.read_bytes()).hexdigest()
    if current_hash not in (journal['original_sha256'],journal['new_sha256']):
        raise ValueError('Installed executable changed; refusing rollback')
    temp=checked_path(root,'.updates/sherif/rollback.tmp')
    with temp.open('wb') as f:f.write(content);f.flush();os.fsync(f.fileno())
    os.replace(temp,target);journal_path.unlink()
    return True


def _install_sherif_candidate(root, package, envelope, previous_envelope, current, device_id=None):
    """Prepare/test signed EXE replacement offline only; caller must run independently after SHERIF exits."""
    root=Path(root).resolve();package=Path(package).resolve()
    if not package.is_relative_to(checked_path(root,'.updates/sherif')):
        raise ValueError('Candidate must be inside the local update staging directory')
    keys=read_json(checked_path(root,'update_public_keys.json'))
    manifest=verify_envelope(envelope,keys)
    # A device-targeted release must never become unrestricted when identity is absent.
    if manifest.get('audience') == 'devices' and not device_id:
        raise ValueError('Device identity required for targeted update')
    validate_manifest(manifest,current,device_id=device_id,sherif_exe=True)
    item=_sherif_exe_item(manifest);previous=verify_envelope(previous_envelope,keys)
    previous_item=_sherif_exe_item(previous)
    compatibility_contract(previous)
    if manifest['database_compatibility']['format']!=previous['database_compatibility']['format']:
        raise ValueError('Database format differs; update stopped')
    if package.stat().st_size!=manifest['package_size'] or hashlib.sha256(package.read_bytes()).hexdigest()!=manifest['package_sha256']:
        raise ValueError('Package digest differs')
    with zipfile.ZipFile(package) as archive:
        entries=archive.infolist()
        if len(entries)!=1 or entries[0].filename!='pos.exe' or entries[0].flag_bits & 1 or entries[0].file_size!=item['size']:
            raise ValueError('Invalid SHERIF package inventory')
        content=archive.read(entries[0])
    if len(content)!=item['size'] or not content.startswith(b'MZ') or hashlib.sha256(content).hexdigest()!=item['sha256']:
        raise ValueError('SHERIF executable integrity check failed')
    if installed_pos_image_present(root,'pos.exe'):raise RuntimeError('SHERIF is still running')
    target=checked_path(root,'pos.exe');assert_replaceable(target)
    original=target.read_bytes()
    if len(original)!=previous_item.get('size') or hashlib.sha256(original).hexdigest()!=previous_item.get('sha256'):
        raise ValueError('Installed executable has no signed rollback identity')
    journal_path=checked_path(root,'.updates/sherif/transaction.json')
    if journal_path.exists():raise RuntimeError('Existing update transaction requires recovery')
    rollback=checked_path(root,'.updates/sherif/rollback/pos.exe');rollback.parent.mkdir(parents=True,exist_ok=True)
    with rollback.open('wb') as f:f.write(original);f.flush();os.fsync(f.fileno())
    journal={'previous_envelope':previous_envelope,'original_sha256':previous_item['sha256'],'new_sha256':item['sha256']}
    atomic_json(journal_path,journal)
    temp=checked_path(root,'.updates/sherif/new-pos.tmp')
    try:
        with temp.open('wb') as f:f.write(content);f.flush();os.fsync(f.fileno())
        if installed_pos_image_present(root,'pos.exe'):raise RuntimeError('SHERIF started during update')
        assert_replaceable(target);os.replace(temp,target)
    except BaseException:
        _recover_sherif_update(root)
        raise
    return {'state':'awaiting_health','release_seq':manifest['release_seq']}


def recover_sherif_update(root):
    root=Path(root).resolve()
    handle=lock_file(checked_path(root,'.updates/sherif/worker.lock'),timeout=0)
    try:return _recover_sherif_update(root)
    finally:handle.close()


def install_sherif_candidate(root, package, envelope, previous_envelope, current, device_id=None):
    root=Path(root).resolve()
    handle=lock_file(checked_path(root,'.updates/sherif/worker.lock'),timeout=0)
    try:return _install_sherif_candidate(root,package,envelope,previous_envelope,current,device_id)
    finally:handle.close()


def mark_update_healthy(root=ROOT):
    root = Path(root)
    atomic_json(root/".updates/startup-health.json",dict(version_info(root),pid=os.getpid(),state="ready"))
    path = root / ".updates" / "transaction.json"
    journal = read_json(path)
    if journal.get("state") == "trial" and journal.get("attempted"):
        journal["state"] = "healthy"
        atomic_json(root / ".updates" / "last_good.json", journal)
        path.unlink(missing_ok=True)
        atomic_json(root / ".updates" / "result.json",
                    {"state": "installed", "release_seq": journal["release_seq"]})


def _local_db_for(root):
    import os
    if os.environ.get('SHERIF_DATA_DIR') and Path(root).resolve()==ROOT.resolve():
        from sherif_paths import local_db
        return local_db()
    return Path(root)/'abu_zaid_local.db'


def device_identity(root):
    db=_local_db_for(root)
    if not db.is_file():
        return None
    with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True,timeout=2)) as conn:
        meta=dict(conn.execute("SELECT key,value FROM local_meta WHERE key IN ('device_id','bound_device_id','bound_branch_id','device_token','device_active','server_enrolled','setup_complete','device_number')"))
    if (not meta.get('device_token') or meta.get('device_active') != '1'
            or meta.get('server_enrolled') != '1'
            or meta.get('bound_device_id') != meta.get('device_id')
            or not str(meta.get('bound_branch_id') or '').isdigit() or int(meta['bound_branch_id']) <= 0):
        return None
    return {'device_id':meta['bound_device_id'],'branch_id':int(meta['bound_branch_id']),'device_number':meta.get('device_number'),
            'headers':{'X-Device-ID':meta['bound_device_id'],'X-Device-Token':meta['device_token'],'X-Updater-Protocol':str(UPDATER_PROTOCOL),'X-Updater-Automatic':'1' if automatic_policy(root)['enabled'] else '0'}}


def installer_baseline(root):
    """A signed installer baseline proves code/health, never a DB comparison."""
    try:
        root=Path(root);marker=read_json(root/'.updates/installer-baseline.json')
        current=version_info(root)
        if marker.get('release_seq')!=current['release_seq']:return None
        manifest=verify_envelope(read_json(root/'.updates/runtime-envelope.json'),read_json(root/'update_public_keys.json'))
        if manifest['release_seq']!=current['release_seq'] or manifest['package_sha256']!=marker.get('package_sha256'):return None
        launcher=manifest.get('installer_launcher_sha256')
        if launcher and hashlib.sha256((root/'AbuZaidPOS.exe').read_bytes()).hexdigest()!=launcher:return None
        for row in manifest['files']:
            p=checked_path(root,row['path'])
            if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:return None
        healthy=read_json(root/'.updates/startup-health.json')
        if healthy.get('state')!='ready' or healthy.get('release_seq')!=current['release_seq']:return None
        if (root/'.updates/transaction.json').exists():return None
        return manifest['package_sha256']
    except (OSError,ValueError,KeyError,TypeError):return None


def report_status(root):
    identity=device_identity(root)
    if not identity:
        return
    body=dict(version_info(root),state=status()['state'])
    result=read_json(Path(root)/'.updates'/'result.json')
    body['result']=result.get('state','')
    value=status()
    body['error_type']=value.get('error_type')
    body['http_status']=value.get('http_status')
    body['error_phase']=value.get('phase')
    body['idle_blocked_by']=value.get('idle_blocked_by')
    # Preserve the last failed attempt while a new attempt is in progress.
    # Only fixed-format diagnostic fields leave the machine, never exception text.
    previous=read_json(Path(root)/'.updates/last-check-error.json')
    body['last_failure']=safe_diagnostic(previous)
    body['error_code']=safe_diagnostic(value).get('error_code')
    body['error_errno']=safe_diagnostic(value).get('error_errno')
    body['error_winerror']=safe_diagnostic(value).get('error_winerror')
    body['error_file']=safe_diagnostic(value).get('error_file')
    events=diagnostic_outbox(root).get('events',[])
    body['diagnostic_events']=[event for event in events if valid_diagnostic_event(event)][:4]
    good=read_json(Path(root)/'.updates/last_good.json')
    audit=good.get('audit_id','')
    comparison=read_json(Path(root)/'.updates/audits'/audit/'comparison.json') if re.fullmatch(r'[a-zA-Z0-9_-]{1,120}',audit) else {}
    body['health_confirmed']=bool(result.get('state')=='installed' and result.get('release_seq')==body['release_seq'] and good.get('release_seq')==body['release_seq']
        and not (Path(root)/'.updates/transaction.json').exists()
        and value.get('state')!='recovery_failed')
    body['data_unchanged']=comparison.get('unchanged') is True
    baseline=installer_baseline(root)
    if baseline and not body['health_confirmed']:
        body.update(result='installed',health_confirmed=True,data_unchanged=False,installer_package_sha256=baseline)
    body['updater_protocol']=UPDATER_PROTOCOL
    while body['diagnostic_events'] and len(json.dumps(body).encode())>4096:
        body['diagnostic_events'].pop()
    headers=dict(identity['headers'], **{'Content-Type':'application/json'})
    atomic_json(Path(root)/'.updates/pending-update-status.json',body)
    reply=json.loads(fetch(api_base(root)+'/updates/status',8192,headers=headers,body=json.dumps(body).encode()))
    if reply.get('accepted') is not True:raise ValueError('Server did not acknowledge update report')
    acknowledge_diagnostics(root,reply.get('accepted_event_ids',[]))
    (Path(root)/'.updates/pending-update-status.json').unlink(missing_ok=True)
    if body['health_confirmed'] and (body['data_unchanged'] or baseline):
        atomic_json(Path(root)/'.updates/report-ack.json',{'release_seq':body['release_seq'],'device_id':identity['device_id'],'audit_id':audit,'confirmed_at':int(time.time())})


def python_helper(root=ROOT):
    import builtins
    if getattr(builtins,'_sherif_update_host',False):
        return str(Path(root)/'AbuZaidPOS.exe')
    standalone=Path(root)/'AbuZaidUpdater.exe'
    if standalone.is_file():
        return str(standalone)
    if not getattr(sys, "frozen", False):
        return sys.executable
    if os.name == "nt":
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                key = winreg.OpenKey(hive, "Software\\Python\\PythonCore\\" +
                                     ".".join(map(str, sys.version_info[:2])) + "\\InstallPath")
                with key:
                    path = Path(winreg.QueryValueEx(key, "ExecutablePath")[0])
                if path.is_absolute() and path.is_file() and path.name.lower() == "python.exe":
                    return str(path)
            except OSError:
                pass
    return None


class UpdateDeferred(Exception):pass


def download_safety_reason(root):
    try:
        import streamlit.runtime
        runtime=streamlit.runtime.get_instance()
        for info in runtime._session_mgr.list_sessions():
            state=info.session.session_state
            for key in ('cart','pos_success_pending','_sale_in_progress','_sale_draft_save_failed','_update_operation_in_progress'):
                if state[key] if key in state else False:return 'sale_or_financial_operation'
        if draft_pending(root):return 'saved_sale_draft'
        store=sys.modules.get('offline_store')
        if store is None:return 'application_initializing'
        for name in ('_SYNC_LOCK','_LOCK'):
            lock=getattr(store,name,None)
            if lock is None or not lock.acquire(blocking=False):return 'operation_running'
            lock.release()
        return None
    except Exception:return 'safety_not_confirmed'


def require_safe_download(root):
    reason=download_safety_reason(root)
    if reason:
        _STATUS.update(state='deferred_until_safe',idle_blocked_by=reason)
        raise UpdateDeferred(reason)


def check_and_stage(root):
    with _CHECK_LOCK:
        if _SCHEDULED:
            restore_scheduled_status(root)
            return
        try:return _check_and_stage(root)
        except UpdateDeferred:return


def _check_and_stage(root):
    root = Path(root)
    trust = checked_path(root, "update_public_keys.json")
    if not trust.is_file() or not read_json(trust):
        _STATUS.update(state="trust_not_configured")
        return
    identity=device_identity(root)
    if not identity:
        _STATUS.update(state='device_required')
        return
    revision=identity_revision(identity)
    headers=identity['headers']
    _STATUS.update(state='checking_updates',phase='manifest_fetch')
    try:
        envelope = json.loads(fetch(api_base(root) + "/updates/latest?component=windows", 512 * 1024,headers=headers))
    except urllib.error.HTTPError as exc:
        if exc.code==404:
            _STATUS.update(state='outside_distribution');return
        if exc.code in (409,423):
            _STATUS.update(state='bootstrap_required' if exc.code==409 else 'waiting_for_pilot')
            return
        raise
    _STATUS.update(phase='manifest_verification')
    manifest = verify_envelope(envelope, read_json(trust))
    current = version_info(root)
    available=manifest.get('release_seq')
    if type(available) is not int or manifest.get('component')!='windows':
        raise ValueError('Invalid release sequence')
    files=manifest.get('files')
    is_sherif_pos=isinstance(files,list) and any(isinstance(item,dict) and item.get('path')=='pos.exe' for item in files)
    validate_manifest(manifest,dict(current,release_seq=-1),device_id=identity['device_id'],sherif_exe=is_sherif_pos)
    if revision!=identity_revision(device_identity(root)):
        _STATUS.update(state='checking_updates',checked_identity=None)
        raise UpdateDeferred('device_registration_changed')
    _STATUS.update(installed_release_seq=current['release_seq'],available_release_seq=available,last_update_check=int(time.time()),checked_identity=revision)
    if available < current['release_seq']:
        _STATUS.update(state='channel_behind',phase='complete');return
    if available == current["release_seq"]:
        _STATUS.update(state='current',phase='complete',error_type=None,http_status=None,reason=None)
        (root/'.updates/last-check-error.json').unlink(missing_ok=True)
        return
    if read_json(root / ".updates" / "blocked.json").get("release_seq") == manifest["release_seq"]:
        _STATUS.update(state="blocked_release")
        return
    failed=read_json(root/'.updates/failed-package.json')
    if (failed.get('release_seq')==available and failed.get('package_sha256')==manifest['package_sha256']):
        # A temporary Windows lock or transport failure must not permanently quarantine
        # a correctly signed package. Signature/health failures remain fail-closed.
        transient=failed.get('error_type') in ('PermissionError','OSError','TimeoutError','ConnectionError','URLError')
        if not transient or time.time()-failed.get('time',0)<60:
            _STATUS.update(state='install_failed',phase='failed_package_retry_wait' if transient else 'failed_package_suppressed',
                error_type=failed.get('error_type'),reason='Temporary failure; retry scheduled' if transient else 'Signed package failed validation; awaiting a corrected approved package')
            return
    # The legacy scheduler cannot safely install a onefile SHERIF update.
    # Keep it blocked until the independent worker is wired into the lifecycle.
    if is_sherif_pos:
        _STATUS.update(state='exe_requires_supervisor',phase='worker_not_connected')
        return
    if manifest["kind"] == "exe" and (read_json(root / "update_launcher.json").get("supervised") is not True or not automatic_policy(root)['enabled']):
        _STATUS.update(state="exe_requires_supervisor")
        return
    highest = read_json(root / ".updates" / "highest_seen.json").get("release_seq", 0)
    if manifest["release_seq"] < highest:
        raise ValueError("Signed release replay rejected")
    atomic_json(root / ".updates" / "highest_seen.json", {"release_seq": manifest["release_seq"]})
    interpreter = python_helper(root)
    if not interpreter:
        _STATUS.update(state="helper_required")
        return
    stage = checked_path(root, ".updates/staged")
    stage.mkdir(parents=True, exist_ok=True)
    package = stage / "package.zip"
    part = stage / "package.part"
    if not package.exists() or hashlib.sha256(package.read_bytes()).hexdigest() != manifest["package_sha256"]:
        _STATUS.update(state='downloading',phase='package_download')
        count = fetch(api_base(root) + "/updates/packages/" + manifest["package_sha256"] + ".zip",
                      manifest["package_size"], part, headers=headers)
        if count != manifest["package_size"] or hashlib.sha256(part.read_bytes()).hexdigest() != manifest["package_sha256"]:
            part.unlink(missing_ok=True)
            raise ValueError("Incomplete update download")
        os.replace(part, package)
    _STATUS.update(phase='package_verification',diagnostic_file=None)
    extract_verified(package, manifest, checked_path(root, ".updates/preflight"))
    _STATUS.update(phase="staging_metadata",diagnostic_file=None)
    atomic_json(stage / "envelope.json", envelope)
    _STATUS.update(phase="worker_bootstrap")
    if schedule_after_exit(root, interpreter, "apply",restart=automatic_policy(root)["enabled"]):
        _STATUS.update(state="ready_after_exit",phase="waiting_owner_exit",available_version=manifest["version"])
        (root/".updates/last-check-error.json").unlink(missing_ok=True)


def _independent_worker_host(root, requested):
    root=Path(root)
    if Path(requested).name.lower()!='abuzaidpos.exe':return requested
    manifest=verify_envelope(read_json(root/'.updates/runtime-envelope.json'),read_json(root/'update_public_keys.json'))
    allowed=set(manifest.get('approved_worker_host_sha256',[]))
    helper=root/'AbuZaidUpdater.exe'
    if helper.is_file() and hashlib.sha256(helper.read_bytes()).hexdigest() in allowed:return str(helper)
    descriptor=manifest.get('worker_bootstrap',{})
    digest=descriptor.get('package_sha256','')
    size=descriptor.get('package_size',0)
    if not re.fullmatch(r'[a-f0-9]{64}',digest) or type(size) is not int or not 0<size<=MAX_PACKAGE:
        raise ValueError('Signed independent update host descriptor is missing')
    if descriptor.get('file_sha256') not in allowed:raise ValueError('Untrusted independent host digest')
    identity=device_identity(root)
    if not identity:raise ValueError('Approved device identity is required for the update host')
    cache=checked_path(root,'.updates/host-cache');cache.mkdir(parents=True,exist_ok=True)
    package=cache/(digest+'.zip')
    if not package.exists() or hashlib.sha256(package.read_bytes()).hexdigest()!=digest:
        part=cache/(digest+'.part')
        count=fetch(api_base(root)+'/updates/packages/'+digest+'.zip',size,part,headers=identity['headers'])
        if count!=size or hashlib.sha256(part.read_bytes()).hexdigest()!=digest:
            part.unlink(missing_ok=True);raise ValueError('Independent host package integrity failed')
        os.replace(part,package)
    with zipfile.ZipFile(package) as archive:data=archive.read('AbuZaidPOS.exe')
    if len(data)!=descriptor.get('file_size') or hashlib.sha256(data).hexdigest()!=descriptor['file_sha256']:
        raise ValueError('Independent update host integrity failed')
    temporary=helper.with_name(helper.name+'.host-part');temporary.write_bytes(data);os.replace(temporary,helper)
    return str(helper)


def schedule_after_exit(root, interpreter, action, restart=False, runtime_recovery=False):
    global _SCHEDULED
    with _THREAD_LOCK:
        if _SCHEDULED:
            return False
        ticket = root / ".updates" / ("exit-" + str(os.getpid()) + "-" + os.urandom(8).hex() + ".json")
        info={"pid":os.getpid(),"action":action,"clean_exit":False,"restart":bool(restart)}
        if runtime_recovery:
            if action!='apply' or not restart:raise ValueError('Invalid recovery action')
            info['purpose']='runtime-restart'
        atomic_json(ticket,info)
        # Only finish_stopped_update may certify the guarded, fully stopped exit.
        # Normal interpreter teardown is not proof that a sale or sync was safe.
        interpreter=_independent_worker_host(root,interpreter)
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        command=[interpreter,'--'+action+'-after-exit',str(os.getpid()),str(ticket)]
        if Path(interpreter).name.lower() != 'abuzaidupdater.exe':
            command=[interpreter,'-B',str(Path(root)/'central_updater.py')]+command[1:]
        worker_process=subprocess.Popen(command,cwd=str(root),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,close_fds=True,creationflags=flags)

        _SCHEDULED = True
        import builtins
        builtins._abuzaid_update_worker_process=worker_process
        builtins._abuzaid_update_exit_ticket=str(ticket)
        lifecycle = getattr(builtins, '_abuzaid_update_lifecycle', None)
        if lifecycle and lifecycle['pid'] == os.getpid():
            lifecycle['worker_globals']['_SCHEDULED'] = True
        return True

def request_rollback(root=ROOT):
    root = Path(root)
    last=read_json(root/'.updates/last_good.json')
    if not last:
        raise ValueError('مفيش إصدار سابق محفوظ')
    assert_rollback_compatible(root,last)
    interpreter = python_helper(root)
    if not interpreter:
        raise ValueError("محتاج تجهيز مشغّل التحديث الأول")
    if _STATUS.get("state") == "ready_after_exit":
        raise ValueError("في تحديث متجهز للإغلاق الحالي؛ خلّصه قبل طلب الرجوع")
    if not schedule_after_exit(root, interpreter, "rollback",restart=automatic_policy(root)["enabled"]):
        raise ValueError("في عملية تحديث أو رجوع متجهزة للإغلاق الحالي")
    _STATUS.update(state="rollback_after_exit")


def wait_for_update_owner_exit(pid,root,timeout=120):
    """Bounded wait for the actual owner, never for a stale/reused PID."""
    import ctypes
    from ctypes import wintypes
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    k.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];k.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=k.OpenProcess(0x100000|0x1000,False,int(pid))
    if not handle:
        if ctypes.get_last_error()==87:return True
        raise OSError('Cannot verify update owner')
    try:
        name=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(name))
        if not k.QueryFullProcessImageNameW(handle,0,name,ctypes.byref(size)):raise OSError('Cannot identify update owner')
        if Path(name.value).resolve()!=Path(root).resolve()/'AbuZaidPOS.exe':return True
        result=k.WaitForSingleObject(handle,int(timeout*1000))
        if result==0:return True
        if result==258:return False
        raise OSError('Cannot wait for update owner')
    finally:k.CloseHandle(handle)


def worker(pid, ticket, root=ROOT, action="apply"):
    if os.name != "nt":
        raise RuntimeError("Automatic installation is Windows-only")
    if not wait_for_update_owner_exit(pid,root,120):
        atomic_json(Path(root)/'.updates/worker-wait.json',{'state':'owner_still_running','pid':pid,'time':int(time.time())})
        return
    root = Path(root)
    ticket = checked_path(root, ".updates/" + Path(ticket).name)
    exit_info=read_json(ticket)
    if (exit_info.get('pid')!=pid or exit_info.get('action')!=action
            or set(exit_info)-{'pid','action','clean_exit','restart','purpose'} or type(exit_info.get('restart',False)) is not bool
            or exit_info.get('purpose') not in (None,'runtime-restart')
            or (exit_info.get('purpose')=='runtime-restart' and (action!='apply' or not exit_info['restart']))):
        return
    # Legacy clean_exit certificates are not an installation prerequisite.
    # Actual process termination, exclusive lock and install_staged guards apply.
    lock = lock_file(checked_path(root, ".updates/app.lock"))
    expected=None
    try:
        if (root / ".updates" / "transaction.json").exists():
            return
        if exit_info.get('purpose')=='runtime-restart':
            # Reopen the same signed code; do not install a package or alter data.
            expected=None
        elif action == "rollback":
            journal = read_json(root / ".updates" / "last_good.json")
            if journal:
                restore_files(root, journal, block_release=False)
                (root / ".updates" / "last_good.json").unlink(missing_ok=True)
        else:
            install_staged(root)
            expected=version_info(root)['release_seq']
    except UpdateDeferred:
        _STATUS.update(state='deferred_until_safe',idle_blocked_by='distribution_not_confirmed')
    except Exception as exc:
        failed=read_json(root/'.updates/staged/envelope.json')
        try:
            failed=verify_envelope(failed,read_json(root/'update_public_keys.json'))
            atomic_json(root/'.updates/failed-package.json',{'release_seq':failed['release_seq'],'package_sha256':failed['package_sha256'],'error_type':type(exc).__name__,'time':int(time.time())})
        except Exception:pass
        _record_update_error(root,exc)
        atomic_json(root/'.updates/worker_error.json',safe_diagnostic(_STATUS))
        atomic_json(root/'.updates/result.json',{'state':'install_failed'})
        _STATUS.update(state='install_failed')
        try:report_status(root)
        except Exception:pass
        if (root/'.updates/transaction.json').exists():return
    finally:
        lock.close()
    if exit_info.get('restart'):
        restart_and_verify(root,expected)


def launch_supervised(root=ROOT):
    """Optional shortcut target: pythonw central_updater.py --launch.
    Required before enabling EXE releases; never kills an application process.
    """
    root = Path(root)
    lock = lock_file(checked_path(root, ".updates/app.lock"))
    launched_trial = None
    try:
        journal = read_json(root / ".updates" / "transaction.json")
        if journal and (journal["state"] == "installing" or journal.get("attempted")):
            restore_files(root, journal)
        elif journal and journal['state'] == 'trial':
            launched_trial = journal['release_seq']
    finally:
        lock.close()
    process = subprocess.Popen([str(checked_path(root, "AbuZaidPOS.exe"))], cwd=str(root))
    process.wait()
    # No automatic relaunch after a failure: leave the restored version ready.
    lock = lock_file(checked_path(root, ".updates/app.lock"), timeout=60)
    try:
        journal = read_json(root / ".updates" / "transaction.json")
        if journal and journal["state"] == "trial" and journal['release_seq'] == launched_trial:
            restore_files(root, journal)
    finally:
        lock.close()


def identity_revision(identity):
    if not identity:return None
    return hashlib.sha256(json.dumps([identity['device_id'],identity['branch_id'],identity.get('device_number'),
        identity['headers'].get('X-Device-Token','')],separators=(',',':')).encode()).hexdigest()


def confirmed_current(value, root=ROOT):
    try:
        current=version_info(root)
        if (Path(root)/'.updates/transaction.json').exists():return False
        healthy=read_json(Path(root)/'.updates/startup-health.json')
        if healthy.get('release_seq')!=current['release_seq'] or healthy.get('state')!='ready':return False
        return (value.get('state')=='current' and
            type(value.get('available_release_seq')) is int and
            value['available_release_seq']==current['release_seq'] and
            value.get('installed_release_seq')==current['release_seq'] and
            value.get('checked_identity') is not None and
            value['checked_identity']==identity_revision(device_identity(root)) and
            0<=time.time()-value.get('last_update_check',0)<=300)
    except (OSError,ValueError,TypeError,sqlite3.Error):return False


def status():
    result = dict(_STATUS)
    try:
        result.update(version_info())
    except (OSError, ValueError):
        pass
    if result.get('state')=='current' and not confirmed_current(result):result['state']='checking_updates'
    return result


def start_update_service(root=ROOT):
    global _STARTED, _APP_LOCK, _STATUS, _SCHEDULED, _CHECK_LOCK
    if os.name != "nt":
        return
    # SHERIF onefile updates remain disabled until its independent worker and trust are provisioned.
    if getattr(sys, "frozen", False) and Path(sys.executable).name.casefold() == "pos.exe":
        return
    with _THREAD_LOCK:
        if _STARTED:
            start_idle_monitor(root)
            return
        root = Path(root).resolve()
        # Preserve the same process lock when Streamlit reloads a changed module.
        # A bootstrap must not stop a working session or create a second updater.
        import builtins
        lifecycle = getattr(builtins, '_abuzaid_update_lifecycle', None)
        legacy = None
        if lifecycle and lifecycle['pid'] == os.getpid() and lifecycle['root'] == str(root):
            legacy = lifecycle['worker_globals']
            _CHECK_LOCK = lifecycle['check_lock']
        else:
            for thread in threading.enumerate():
                target = getattr(thread, '_target', None)
                namespace = getattr(target, '__globals__', {})
                if (thread.name == 'abuzaid-update-check' and thread.is_alive()
                        and namespace.get('_APP_LOCK') is not None
                        and Path(namespace.get('ROOT', '')).resolve() == root):
                    legacy = namespace
                    break
        if legacy is not None:
            _APP_LOCK = legacy['_APP_LOCK']
            _STATUS = legacy['_STATUS']
            _SCHEDULED = bool(legacy.get('_SCHEDULED', False))
            legacy['check_and_stage'] = check_and_stage
            legacy['report_status'] = report_status
            _STARTED = True
            start_idle_monitor(root)
            builtins._abuzaid_update_lifecycle = {'pid': os.getpid(), 'root': str(root),
                'worker_globals': legacy, 'check_lock': _CHECK_LOCK}
            return
        prestart=getattr(builtins,'_sherif_prestart_app_lock',None)
        try:
            if (isinstance(prestart,dict) and prestart.get('pid')==os.getpid()
                    and prestart.get('root')==str(root) and not prestart['handle'].closed
                    and Path(prestart['handle'].name).resolve()==root/'.updates/app.lock'):
                _APP_LOCK=prestart['handle']
                del builtins._sherif_prestart_app_lock
            else:_APP_LOCK = lock_file(checked_path(root, ".updates/app.lock"),timeout=2)
        except TimeoutError:
            if reject_duplicate_program(root):return
            raise
        journal=read_json(root/'.updates/transaction.json')
        if journal.get('state')=='installing' or (journal.get('state')=='trial' and journal.get('attempted')):
            # Official launcher delegates this to the independent embedded host
            # BEFORE importing main. A direct legacy Streamlit invocation must
            # never attempt to replace its running POS image.
            _APP_LOCK.close();_APP_LOCK=None
            _STATUS.update(state='recovery_required',phase='startup_recovery')
            raise UpdateDeferred('independent_startup_recovery_required')
        recover(root)  # Before the application imports or opens its database.
        _STATUS.update(version_info(root))
        _STARTED = True
        builtins._abuzaid_update_lifecycle = {'pid': os.getpid(), 'root': str(root),
            'worker_globals': globals(), 'check_lock': _CHECK_LOCK}
        def run():
            while True:
                try:
                    check_and_stage(root)
                except Exception as exc:
                    _record_update_error(root,exc)
                try:
                    report_status(root)
                except Exception:
                    pass
                if _STATUS["state"] in ("ready_after_exit", "rollback_after_exit"):
                    return
                time.sleep(30 if _STATUS["state"] == "device_required" else 60)
        threading.Thread(target=run, name="abuzaid-update-check", daemon=True).start()
        start_idle_monitor(root)


def automatic_policy(root=ROOT):
    value=read_json(Path(root)/'.updates/automatic.json')
    return {'enabled':value.get('enabled') is True,'idle_seconds':max(30,min(600,int(value.get('idle_seconds',90))))}


def quiescing():
    import builtins
    return bool(getattr(builtins,'_abuzaid_update_quiescing',False))


def assert_writes_allowed():
    if quiescing():raise RuntimeError('جاري تحديث البرنامج بعد انتهاء العمل؛ العملية الجديدة لم تُسجل. البرنامج هيفتح تلقائيًا.')


def maintenance_gate():
    if quiescing():
        import streamlit as st
        st.info('جاري تثبيت تحديث آمن؛ البرنامج هيفتح تلقائيًا. البيانات محفوظة.')
        st.stop()


def virtual_pos_state(state):
    try:
        context=state['_pos_memory_context'];owner=tuple(context.owner)
        try:scope=state['_sale_draft_scope']
        except KeyError:scope=None
        return (getattr(context,'virtual_pos',False) is True and len(owner)==2
                and owner[1]!='Cashier' and owner[0]==state['user_id']
                and tuple(state['_pos_actor_key'])==owner and not scope)
    except (KeyError,AttributeError,TypeError):return False


def session_idle_reason(sessions,closing=False,discard_virtual=False,updating=False):
    for info in sessions:
        session=info.session
        runner=getattr(session,'_scriptrunner',None)
        if runner is not None and getattr(runner,'_execing',True):return 'script_running'
        if getattr(getattr(session,'_state',None),'name',None) not in ('APP_NOT_RUNNING','SHUTDOWN_REQUESTED'):
            return 'session_running_or_unknown'
        state=session.session_state
        def value(key,default=None):
            try:return state[key]
            except KeyError:return default
        flags=('pos_success_pending','_sale_in_progress','_sale_draft_save_failed','_update_operation_in_progress') if closing else ('cart','pos_success_pending','_sale_in_progress','_sale_draft_save_failed','_update_operation_in_progress')
        if virtual_pos_state(state) and (closing or discard_virtual or getattr(value('_pos_memory_context'),'_closed',False)):
            flags=('_sale_in_progress','_update_operation_in_progress')
        if updating:
            # A committed sale's acknowledgement screen is not a financial operation.
            # The running-script, cart, transaction and durable-draft guards still apply.
            flags=tuple(key for key in flags if key!='pos_success_pending')
        if any(value(k) for k in flags):
            return 'sale_or_receipt_pending'
        if not updating and not closing and value('logged_in') and value('page','🏠 الرئيسية واللوحة') not in ('🏠 الرئيسية واللوحة','🛒 نقطة البيع (POS)'):
            return 'administrative_form_open'
    return None


def windows_idle_seconds():
    import ctypes
    from ctypes import wintypes
    class InputInfo(ctypes.Structure):_fields_=[('cbSize',wintypes.UINT),('dwTime',wintypes.DWORD)]
    info=InputInfo();info.cbSize=ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):raise OSError('Input activity unavailable')
    return ((ctypes.windll.kernel32.GetTickCount()-info.dwTime)&0xffffffff)/1000


def draft_pending(root):
    with closing(sqlite3.connect(_local_db_for(root).resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as conn:
        for row in conn.execute("SELECT value FROM local_meta WHERE key LIKE 'pos_sale_draft:v1:%'"):
            draft=json.loads(row[0])
            if draft.get('state') not in ('open','completed'):return True
            if draft.get('state')=='open' and draft.get('cart'):return True
    return False


def pending_financial_reason(root):
    try:
        with closing(sqlite3.connect(_local_db_for(root).resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as conn:
            for table in ('invoices','sync_queue','erp_outbox'):
                if conn.execute('SELECT 1 FROM '+table+" WHERE COALESCE(sync_status,'pending') NOT IN ('synced','ignored','cancelled_reset') LIMIT 1").fetchone():return 'pending_financial_operations'
            if conn.execute('SELECT 1 FROM transfer_logs WHERE receipt_pending=1 LIMIT 1').fetchone():return 'pending_transfer'
            if conn.execute("SELECT 1 FROM exception_settlements WHERE sync_status='pending' LIMIT 1").fetchone():return 'pending_settlement'
            if conn.execute("SELECT 1 FROM local_meta WHERE key IN ('branch_reset_guard','device_reconfigure_intent','device_lifecycle_intent')").fetchone():return 'pending_administrative_operation'
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='local_shift_uploads'").fetchone():
                columns={row[1] for row in conn.execute('PRAGMA table_info(local_shift_uploads)')}
                extra=" AND COALESCE(u.cancelled_reset_id,'')=''" if 'cancelled_reset_id' in columns else ''
                if conn.execute('SELECT 1 FROM shift_closures s LEFT JOIN local_shift_uploads u ON u.branch_id=s.branch_id AND u.shift_date=s.shift_date AND u.shift_number=s.shift_number WHERE u.synced_at IS NULL'+extra+' LIMIT 1').fetchone():return 'pending_shift'
            elif conn.execute('SELECT 1 FROM shift_closures LIMIT 1').fetchone():return 'pending_shift'
        return None
    except (sqlite3.Error,OSError,ValueError):return 'financial_safety_not_confirmed'


def installation_sessions(runtime):
    """Only live sessions and currently executing scripts can block replacement."""
    sessions=list(runtime._session_mgr.list_sessions())
    active={id(info.session) for info in runtime._session_mgr.list_active_sessions()}
    result=[]
    for info in sessions:
        runner=getattr(info.session,'_scriptrunner',None)
        if id(info.session) in active or (runner is not None and getattr(runner,'_execing',True)):
            result.append(info)
    return result


def try_idle_shutdown(root, runtime, recovery=False, explicit=False):
    import builtins
    if quiescing():return True
    # A quiet keyboard or a stale health file is never permission to stop POS.
    if not _SCHEDULED and not (explicit and getattr(builtins,'_abuzaid_program_exit_requested',False)):
        _STATUS['idle_blocked_by']='no_authorized_exit';return False
    browser_closing=bool(getattr(builtins,"_abuzaid_browser_close_requested",False))
    # Persisted queues are audited, not mistaken for a live sale.
    reason=session_idle_reason((installation_sessions(runtime) if _SCHEDULED else runtime._session_mgr.list_sessions()),closing=browser_closing,discard_virtual=explicit,updating=_SCHEDULED)
    if reason:_STATUS['idle_blocked_by']=reason;return False
    store=sys.modules.get('offline_store')
    if store is None and not recovery:_STATUS['idle_blocked_by']='application_initializing';return False
    held=[]
    try:
        sync=sys.modules.get('auto_sync')
        if sync is not None:
            lock=getattr(sync,'_LOCK',None)
            if lock is None or not lock.acquire(blocking=False):return False
            held.append(lock)
            if sync._STATUS.get('state')=='checking':
                _STATUS['idle_blocked_by']='synchronization_running';return False
        for name in (('_SYNC_LOCK','_LOCK') if store is not None else ()):
            lock=getattr(store,name,None)
            if lock is None or not lock.acquire(blocking=False):
                _STATUS['idle_blocked_by']='synchronization_running';return False
            held.append(lock)
        if browser_closing:
            if runtime._session_mgr.list_active_sessions() or not durable_carts_match(root,(installation_sessions(runtime) if _SCHEDULED else runtime._session_mgr.list_sessions())):return False
        elif _SCHEDULED:
            if not durable_carts_match(root,installation_sessions(runtime)):_STATUS['idle_blocked_by']='unpersisted_active_cart';return False
        elif draft_pending(root):_STATUS['idle_blocked_by']='saved_sale_draft';return False
        # Recheck scripts after locking out synchronization; never stop an executing sale.
        if session_idle_reason((installation_sessions(runtime) if _SCHEDULED else runtime._session_mgr.list_sessions()),closing=browser_closing,discard_virtual=explicit,updating=_SCHEDULED):return False
        builtins._abuzaid_update_quiescing=True
        _STATUS.update(state='restarting_for_update',idle_blocked_by='')
        if sync is not None:
            sync._STOP.set();sync._PENDING=None
        # Do not let an unavailable internet connection delay local shutdown.
        runtime.stop()  # First complete the existing graceful, idle-approved shutdown.
        arm_stopped_update_exit(root,runtime)
        return True
    except Exception:
        if quiescing():builtins._abuzaid_update_quiescing=False
        raise
    finally:
        for lock in reversed(held):lock.release()




def finish_stopped_update(root, runtime):
    """Exit only this frozen EXE after its idle-approved runtime fully stopped.

    No external PID is terminated. All normal sale/sync/draft guards remain in
    force, and the waiting signed installer still verifies exit code and ticket.
    """
    root=Path(root).resolve()
    if (os.name!='nt' or not getattr(sys,'frozen',False)
            or Path(sys.executable).resolve()!=root/'AbuZaidPOS.exe'
            or not quiescing()):return False
    import builtins
    if not _SCHEDULED and not getattr(builtins,'_abuzaid_program_exit_requested',False):return False
    stopped=runtime.stopped
    if (not stopped.done() or stopped.cancelled() or stopped.exception() is not None
            or getattr(getattr(runtime,'state',None),'name',None)!='STOPPED'):return False
    browser_closing=bool(getattr(builtins,"_abuzaid_browser_close_requested",False))
    if session_idle_reason((installation_sessions(runtime) if _SCHEDULED else runtime._session_mgr.list_sessions()),closing=browser_closing,discard_virtual=bool(getattr(builtins,'_abuzaid_program_exit_requested',False)),updating=_SCHEDULED):return False
    store=sys.modules.get('offline_store')
    if store is None:return False
    held=[]
    try:
        sync=sys.modules.get('auto_sync')
        if sync is not None:
            lock=getattr(sync,'_LOCK',None)
            if lock is None or not lock.acquire(blocking=False):return False
            held.append(lock)
            if sync._STATUS.get('state')=='checking' or not sync._STOP.is_set():return False
        for name in ('_SYNC_LOCK','_LOCK'):
            lock=getattr(store,name,None)
            if lock is None or not lock.acquire(blocking=False):return False
            held.append(lock)
        if browser_closing:
            if runtime._session_mgr.list_active_sessions() or not durable_carts_match(root,(installation_sessions(runtime) if _SCHEDULED else runtime._session_mgr.list_sessions())):return False
        elif _SCHEDULED:
            if not durable_carts_match(root,installation_sessions(runtime)):return False
        elif draft_pending(root):return False
        if session_idle_reason((installation_sessions(runtime) if _SCHEDULED else runtime._session_mgr.list_sessions()),closing=browser_closing,discard_virtual=bool(getattr(builtins,'_abuzaid_program_exit_requested',False)),updating=_SCHEDULED):return False
        if _SCHEDULED:
            current_ticket=getattr(builtins,'_abuzaid_update_exit_ticket',None)
            if not current_ticket:return False
            ticket=Path(current_ticket)
            if (ticket.parent.resolve()!=root/'.updates' or not ticket.name.startswith('exit-'+str(os.getpid())+'-')
                    or not ticket.name.endswith('.json')):return False
            ticket=checked_path(root,'.updates/'+ticket.name)
            info=read_json(ticket)
            if (info.get('pid')!=os.getpid() or info.get('action') not in ('apply','rollback')
                    or info.get('clean_exit') is not False or type(info.get('restart')) is not bool
                    or set(info)-{'pid','action','clean_exit','restart','purpose'}
                    or info.get('purpose') not in (None,'runtime-restart')
                    or (info.get('purpose')=='runtime-restart' and (info['action']!='apply' or not info['restart']))):return False
            # Saved pending operations may close offline, but must not certify an install.
            info['clean_exit']=True
            atomic_json(ticket,info)
        closer=getattr(builtins,'_abuzaid_close_desktop_window',None)
        if callable(closer):closer()
        for stream in (sys.stdout,sys.stderr):
            try:stream.flush()
            except Exception:pass
        os._exit(0)
        return True  # Reached only by the isolated test's exit stub.
    finally:
        for lock in reversed(held):lock.release()


def arm_stopped_update_exit(root,runtime):
    """Keep the launcher alive until its guarded exit is certified or refused."""
    import builtins
    previous=getattr(builtins,'_abuzaid_clean_update_exit_thread',None)
    if previous is not None and previous.is_alive():return
    def finish():
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            try:
                if finish_stopped_update(root,runtime):return
            except Exception as exc:
                _STATUS['shutdown_error_type']=type(exc).__name__
            time.sleep(0.2)
        _STATUS.update(state='shutdown_waiting_for_safe_exit')
        try:report_status(root)
        except Exception:pass
    # A daemon is discarded when Streamlit/launcher returns, before the worker
    # receives its certificate. Hold normal interpreter teardown until the same
    # existing safety checks finish; a timeout still never certifies an exit.
    thread=threading.Thread(target=finish,name='abuzaid-clean-update-exit',daemon=False)
    builtins._abuzaid_clean_update_exit_thread=thread
    thread.start()


def observe_browser_window():
    """Deliver page-close independently of the WebSocket being torn down."""
    if os.name!='nt':return
    import streamlit as st
    from streamlit.components.v2 import component
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    import builtins
    endpoint=getattr(builtins,'_abuzaid_close_endpoint',None)
    if not endpoint:return
    context=get_script_run_ctx()
    if not context:return
    @st.cache_resource(show_spinner=False)
    def close_component():
        return component('abuzaid_desktop_close_v2',js=r'''
        export default function({data}) {
          const slot='__abuzaidCloseV2';
          if (!window[slot]) {
            const state={data}; window[slot]=state;
            const notify=()=>navigator.sendBeacon(state.data.url,
              JSON.stringify({session:state.data.session}));
            window.addEventListener('pagehide',notify);
            window.addEventListener('beforeunload',notify);
          }
          window[slot].data=data;
          // Keep the listener through component rerenders and employee logout.
          // A full document reload naturally removes it; reconnection cancels close.
        }''')
    close_component()(key='abuzaid_desktop_close',height=0,
        data={'url':endpoint,'session':context.session_id})


def start_close_listener(browser_port):
    """Loopback-only, per-process capability. No DB, network, or OS commands."""
    import builtins,secrets
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    if getattr(builtins,'_abuzaid_close_endpoint',None):return
    route='/close/'+secrets.token_hex(32)
    origins={'http://127.0.0.1:'+str(browser_port),'http://localhost:'+str(browser_port)}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            if self.path!=route or self.headers.get('Origin') not in origins:
                self.send_error(403);return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=512:raise ValueError('Invalid notice size')
                notice=json.loads(self.rfile.read(length))
                session=notice['session']
                if not isinstance(session,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}',session):
                    raise ValueError('Invalid session')
                with _THREAD_LOCK:
                    records=getattr(builtins,'_abuzaid_browser_close_notices',{})
                    records[session]={'notice':time.monotonic_ns(),'at':time.monotonic(),'handled':False}
                    builtins._abuzaid_browser_close_notices=records
                self.send_response(204);self.end_headers()
            except (ValueError,KeyError,TypeError):self.send_error(400)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True
    builtins._abuzaid_close_endpoint='http://127.0.0.1:'+str(server.server_port)+route
    builtins._abuzaid_close_server=server
    threading.Thread(target=server.serve_forever,name='abuzaid-close-notice',daemon=True).start()


def durable_carts_match(root,sessions):
    """Read-only proof that closing cannot discard an uncommitted cart edit."""
    with closing(sqlite3.connect(_local_db_for(root).resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as conn:
        for row in conn.execute("SELECT value FROM local_meta WHERE key LIKE 'pos_sale_draft:v1:%'"):
            draft=json.loads(row[0])
            if draft.get('schema')!=1 or draft.get('state') not in ('open','completed') or not isinstance(draft.get('cart'),list):return False
        for info in sessions:
            state=info.session.session_state
            if virtual_pos_state(state):continue
            try:cart=state['cart']
            except KeyError:continue
            if not cart:continue
            try:scope=state['_sale_draft_scope'];expected=state['_sale_draft_record']
            except KeyError:return False
            key='pos_sale_draft:v1:'+json.dumps(scope,sort_keys=True,separators=(',',':'))
            row=conn.execute('SELECT value FROM local_meta WHERE key=?',(key,)).fetchone()
            if not row or not expected:return False
            draft=json.loads(row[0])
            if (draft.get('state')!='open' or draft.get('scope')!=scope or draft.get('cart')!=cart
                    or (draft.get('id'),draft.get('revision'))!=(expected.get('id'),expected.get('revision'))):return False
    return True


def try_browser_close(root,runtime):
    import builtins
    records=getattr(builtins,'_abuzaid_browser_close_notices',{})
    due=[r for r in list(records.values()) if not r['handled'] and time.monotonic()-r['at']>=30]
    if not due:return False
    # F5/logout reloads and another open window cancel closure. Hidden tabs and
    # sleeping WebSockets alone never create an explicit unload notice.
    if runtime._session_mgr.list_active_sessions():
        for r in due:r['handled']=True
        if getattr(builtins,'_abuzaid_browser_close_requested',False):
            builtins._abuzaid_browser_close_requested=False
            builtins._abuzaid_program_exit_requested=False
        return False
    sessions=runtime._session_mgr.list_sessions()
    if session_idle_reason(sessions,closing=True):return False
    if not durable_carts_match(root,sessions):
        _STATUS['idle_blocked_by']='cart_not_confirmed_durable';return False
    _explicit_exit_ticket(root)
    builtins._abuzaid_browser_close_requested=True
    builtins._abuzaid_program_exit_requested=True
    return try_idle_shutdown(root,runtime,explicit=True)



def observe_runtime_stop(root,runtime):
    """Record caller names only; never log locals, arguments, URLs or secrets."""
    if getattr(runtime,'_abuzaid_stop_observed',False):return
    original=runtime.stop
    def observed(*args,**kwargs):
        import builtins,traceback
        callers=[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno}
                 for f in traceback.extract_stack(limit=10)[:-1]]
        intentional=bool(getattr(builtins,'_abuzaid_program_exit_requested',False))
        external_signal=any(f['function']=='_on_signal' for f in callers)
        runtime._abuzaid_external_stop=external_signal
        try:atomic_json(Path(root)/'.updates/runtime-stop.json',{
            'pid':os.getpid(),'time':int(time.time()),'release_seq':version_info(root)['release_seq'],
            'state_before':getattr(getattr(runtime,'state',None),'name',None),
            'update_scheduled':bool(_SCHEDULED),'explicit_exit':intentional,
            'external_signal':external_signal,'callers':callers})
        except Exception:pass
        return original(*args,**kwargs)
    runtime.stop=observed
    runtime._abuzaid_stop_observed=True


def recover_unexpected_runtime(root,runtime):
    """Recover only a fully stopped own runtime, behind all sale/sync guards."""
    import builtins
    if getattr(getattr(runtime,'state',None),'name',None)!='STOPPED':return False
    if not runtime.stopped.done() or runtime.stopped.cancelled() or runtime.stopped.exception() is not None:return False
    explicit=bool(getattr(builtins,'_abuzaid_program_exit_requested',False))
    if not explicit and getattr(runtime,'_abuzaid_external_stop',False):
        builtins._abuzaid_program_exit_requested=True;explicit=True
    if not _SCHEDULED and not explicit:
        if (Path(root)/'.updates/transaction.json').exists():
            _STATUS['idle_blocked_by']='unconfirmed_update_trial';return False
        helper=python_helper(root)
        if not helper:
            _STATUS['idle_blocked_by']='recovery_helper_unavailable';return False
        if not schedule_after_exit(Path(root),helper,'apply',restart=True,runtime_recovery=True):return False
    if not explicit:
        # A persisted draft is recoverable, not a reason to leave a dead runtime
        # permanently open. Unpersisted edits and running operations still block.
        builtins._abuzaid_browser_close_requested=True
    # No external process is killed. The owner exits only after all guards pass.
    return try_idle_shutdown(root,runtime,recovery=True,explicit=True)


def start_idle_monitor(root=ROOT):
    import builtins
    # Closing and runtime recovery must also work offline / before enrollment.
    marker=getattr(builtins,'_abuzaid_idle_monitor',None)
    if marker and marker.is_alive():return
    def monitor():
        while True:
            time.sleep(5)
            try:
                atomic_json(Path(root)/'.updates/runtime.json',{'pid':os.getpid(),'updater_protocol':UPDATER_PROTOCOL,'time':int(time.time()),'state':_STATUS['state'],'idle_blocked_by':_STATUS.get('idle_blocked_by'),'available_release_seq':_STATUS.get('available_release_seq')})
                from streamlit.runtime import Runtime
                runtime=Runtime.instance()
                observe_runtime_stop(root,runtime)
                if recover_unexpected_runtime(root,runtime):return
                if try_browser_close(root,runtime):return
                pending=automatic_policy(root)['enabled'] and restore_scheduled_status(root)
                if not pending:
                    # The original check thread may have ended when this worker was scheduled.
                    # If the bounded helper timed out during a long sale/sleep, resume via
                    # the same serialized signed check path, not a second installer.
                    if _STATUS.get('idle_blocked_by')=='worker_wait_ended':
                        request_update_check(root)
                    continue
                if try_idle_shutdown(root,runtime):return
            except Exception as exc:
                _STATUS['idle_blocked_by']='safety_check_'+type(exc).__name__
    thread=threading.Thread(target=monitor,name='abuzaid-idle-update',daemon=True)
    builtins._abuzaid_idle_monitor=thread;thread.start()


def restart_and_verify(root,expected_sequence=None):
    root=Path(root)
    process=subprocess.Popen([str(checked_path(root,'AbuZaidPOS.exe'))],cwd=str(root),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if expected_sequence is None:return
    deadline=time.monotonic()+120
    recovery_requested=False
    while process.poll() is None:
        result=read_json(root/'.updates/result.json')
        if result.get('state')=='installed' and result.get('release_seq')==expected_sequence:
            _STATUS.update(state='current')
            try:report_status(root)
            except Exception:pass
            return
        if time.monotonic()>deadline and not recovery_requested:
            atomic_json(root/'.updates/health-recovery.json',{'requested':True,'release_seq':expected_sequence})
            _STATUS.update(state='health_check_failed_waiting_idle')
            try:report_status(root)
            except Exception:pass
            recovery_requested=True
        time.sleep(2)
    # Restore code only after the actual launched process exits. No forced stop.
    lock=lock_file(root/'.updates/app.lock')
    try:
        journal=read_json(root/'.updates/transaction.json')
        if journal and journal.get('release_seq')==expected_sequence:
            restore_files(root,journal)
            (root/'.updates/health-recovery.json').unlink(missing_ok=True)
            _STATUS.update(state='rolled_back')
            try:report_status(root)
            except Exception:pass
        else:return
    finally:lock.close()
    subprocess.Popen([str(root/'AbuZaidPOS.exe')],cwd=str(root),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def bootstrap_existing_install(root, expected_device_id):
    """One-time trusted provisioning; never registers a device or opens SQLite for writing."""
    import ast
    root=Path(root).resolve()
    for name in ('main.py','AbuZaidPOS.exe','abu_zaid_local.db','central_updater.py','update_audit.py','update_public_keys.json','.updates/automatic.json'):
        checked_path(root,name)
    if Path(sys.executable).resolve()==(root/'AbuZaidUpdater.exe').resolve():
        raise ValueError('Run the first-time installer from the extracted download folder, not inside the application folder')
    if not (root/'AbuZaidPOS.exe').is_file() or not (root/'main.py').is_file():
        raise ValueError('Existing original POS installation required')
    ensure_initial_program_closed(root)
    identity=device_identity(root)
    if not identity or identity['device_id']!=expected_device_id:
        raise ValueError('Existing device binding incomplete or differs; no identity or database changed')
    source=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'bootstrap'
    trusted=read_json(source/'update_public_keys.json')
    if not trusted:raise ValueError('Embedded central trust missing')
    detached=Path(sys.executable if getattr(sys,'frozen',False) else __file__).parent/'bootstrap-envelope.json'
    envelope=read_json(detached)
    manifest=verify_envelope(envelope,trusted)
    if manifest.get('component')!='updater-bootstrap' or manifest.get('updater_protocol')!=UPDATER_PROTOCOL:
        raise ValueError('Wrong bootstrap manifest')
    if type(manifest.get('expires_at')) is not int or manifest['expires_at']<=time.time():raise ValueError('Bootstrap expired')
    existing_policy=read_json(root/'.updates/automatic.json')
    if existing_policy.get('enabled') is True:
        previous=read_json(root/'.updates/runtime-envelope.json')
        old_payload=verify_envelope(previous,read_json(root/'update_public_keys.json'))
        runtime_rows={r['path']:r for r in old_payload.get('files',[]) if r['path'] in ('central_updater.py','update_audit.py')}
        if set(runtime_rows)=={'central_updater.py','update_audit.py'} and all(hashlib.sha256((root/name).read_bytes()).hexdigest()==row['sha256'] for name,row in runtime_rows.items()):
            print(json.dumps({'already_provisioned':True,'branch_id':identity['branch_id'],'no_files_or_data_changed':True}));return
        raise ValueError('Existing automatic updater requires controlled repair; no downgrade performed')
    inventory=manifest.get('files',[])
    if {r['path'] for r in inventory}!={'central_updater.py','update_audit.py','AbuZaidUpdater.exe','update_public_keys.json'}:
        raise ValueError('Wrong bootstrap inventory')
    contents={}
    for row in inventory:
        content=Path(sys.executable).read_bytes() if row['path']=='AbuZaidUpdater.exe' else (source/row['path']).read_bytes()
        if hashlib.sha256(content).hexdigest()!=row['sha256'] or len(content)!=row['size']:raise ValueError('Bootstrap signature/file mismatch')
        contents[row['path']]=content
    # Validate existing authentication over HTTPS without re-enrolling or exporting credentials.
    approved=json.loads(fetch(api_base(root)+'/updates/bootstrap-check',8192,headers=identity['headers']))
    if approved.get('device_id')!=identity['device_id'] or approved.get('branch_id')!=identity['branch_id'] or approved.get('active') is not True:
        raise ValueError('Server enrollment does not match existing identity')
    keys=read_json(root/'update_public_keys.json')
    for key,value in trusted.items():
        if key in keys and keys[key]!=value:raise ValueError('Conflicting trust anchor')
        keys[key]=value
    contents['update_public_keys.json']=json.dumps(keys,sort_keys=True).encode()
    main=(root/'main.py').read_text(encoding='utf-8-sig')
    hook='from central_updater import start_update_service, mark_update_healthy, show_update_status'
    if 'start_update_service()' not in main:
        main=hook+'\nstart_update_service()\n'+main
    if 'maintenance_gate()' not in main:
        main=main.replace('start_update_service()','start_update_service()\nfrom central_updater import maintenance_gate\nmaintenance_gate()',1)
    if 'mark_update_healthy()' not in main:
        if len(re.findall(r'^initialize_app_database\(\)\s*$',main,re.MULTILINE))!=1:
            raise ValueError('Unrecognized old launcher; no program or data changed')
        main=re.sub(r'^initialize_app_database\(\)\s*$',lambda m:m.group(0)+'\nmark_update_healthy()',main,count=1,flags=re.MULTILINE)
    ast.parse(main)
    sync_path=root/'auto_sync.py'
    if sync_path.is_file():
        sync_source=sync_path.read_text(encoding='utf-8-sig')
        anchor="    with _LOCK:\n        _STATUS.update(state='checking',last_attempt=time.time())"
        if anchor in sync_source:
            sync_source=sync_source.replace(anchor,"    with _LOCK:\n        if _STOP.is_set():return\n        _STATUS.update(state='checking',last_attempt=time.time())",1)
        elif "if _STOP.is_set():return" not in sync_source:
            raise ValueError('Unrecognized sync worker; provisioning left data unchanged')
        ast.parse(sync_source);contents['auto_sync.py']=sync_source.encode('utf-8')
    contents['main.py']=main.encode('utf-8')
    # The policy is set last. main.py is replaced after its dependencies are complete.
    contents['.updates/runtime-envelope.json']=json.dumps(envelope,sort_keys=True).encode()
    contents['update_launcher.json']=json.dumps({'supervised':True,'updater_protocol':2}).encode()
    contents['.updates/automatic.json']=json.dumps({'enabled':True,'idle_seconds':90,'updater_protocol':2},sort_keys=True).encode()
    journal=[];backup=root/'.updates/bootstrap'/str(int(time.time()))
    backup.mkdir(parents=True,exist_ok=False)
    try:
        order=[name for name in contents if name!='main.py']+['main.py']
        for name in order:
            data=contents[name]
            target=root/name;old=target.read_bytes() if target.exists() else None
            journal.append((target,old))
            if old is not None:
                saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes(old)
            target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_name(target.name+'.bootstrap-tmp');temporary.write_bytes(data);os.replace(temporary,target)
        atomic_json(backup/'receipt.json',{'updater_protocol':2,'branch_id':identity['branch_id'],'existing_device_id':identity['device_id'],'database_modified':False,'runtime_confirmation_required':True})
    except Exception:
        for target,old in reversed(journal):
            if old is None:target.unlink(missing_ok=True)
            else:
                temporary=target.with_name(target.name+'.bootstrap-restore');temporary.write_bytes(old);os.replace(temporary,target)
        raise
    print(json.dumps({'bootstrap_configured':True,'branch_id':identity['branch_id'],'updater_protocol':2,'database_modified':False,'runtime_install_success_not_yet_confirmed':True}))


def delegate_trusted_runtime(root=ROOT):
    """Stable helper can run a newer signed engine without replacing its own running EXE."""
    import builtins
    if not getattr(sys,'frozen',False) or getattr(builtins,'_abuzaid_runtime_delegated',False):return False
    envelope=read_json(Path(root)/'.updates/runtime-envelope.json')
    if not envelope:return False
    payload=verify_envelope(envelope,read_json(Path(root)/'update_public_keys.json'))
    # A rebuilt helper contains this baseline. An older signed envelope cannot
    # force it to execute superseded engine files after an offline Setup upgrade.
    baseline=getattr(builtins,'_abuzaid_bundled_engine_seq',-1)
    if type(payload.get('release_seq')) is int and payload['release_seq']<=baseline:return False
    rows={r['path']:r for r in payload.get('files',[]) if r['path'] in ('central_updater.py','update_audit.py')}
    if set(rows)!= {'central_updater.py','update_audit.py'}:raise ValueError('Signed updater runtime inventory incomplete')
    for name,row in rows.items():
        data=(Path(root)/name).read_bytes()
        if len(data)!=row['size'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Updater runtime integrity failed')
    builtins._abuzaid_runtime_delegated=True
    sys.path.insert(0,str(root))
    sys.modules.pop('update_audit',None)
    import runpy
    runpy.run_path(str(Path(root)/'central_updater.py'),run_name='__main__')
    return True


def ensure_initial_program_closed(root):
    # Read the file-sharing state only; never terminate a process or write the POS executable.
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateFileW(str(Path(root)/'AbuZaidPOS.exe'),0x40000000,0,None,3,0,None)
    if handle==ctypes.c_void_p(-1).value:
        raise ValueError('للتهيئة الأولى فقط: ملف البرنامج قيد الاستخدام أو غير متاح للفحص. بعد إنهاء الفاتورة اقفل البرنامج وشغّل أداة التهيئة مرة واحدة. لم يتغير أي ملف أو بيانات.')
    kernel.CloseHandle(handle)


def interactive_bootstrap():
    import ctypes
    try:
        root=ROOT
        if not (root/'AbuZaidPOS.exe').is_file():
            raise ValueError('تعذر العثور على البرنامج بجانب المحدّث. استخدم --diagnose مع مسار التثبيت الصحيح.')
        found=diagnose(root)
        engine='موجود' if found['engine_source_present'] else 'غير موجود'
        summary='الفحص الحالي: محرك التحديث '+engine+'؛ ربط التشغيل '+('موجود' if found['startup_hook_present'] else 'غير موجود')+'؛ مفاتيح التحقق '+('موجودة' if found['trusted_keys_available'] else 'غير مهيأة')+'.'
        answer=ctypes.windll.user32.MessageBoxW(None,summary+'\nهل تريد تهيئة/ترقية المحرك مرة واحدة فقط؟ البرنامج الحالي وقاعدة البيانات وهوية الجهاز لن يتم استبدالهم.','فحص محرك التحديث',0x24)
        if answer!=6:return
        identity=device_identity(root)
        if not identity:raise ValueError('اعتماد الجهاز المحلي غير مكتمل؛ مفيش تغيير للهوية أو قاعدة البيانات.')
        bootstrap_existing_install(root,identity['device_id'])
        subprocess.Popen([str(root/'AbuZaidPOS.exe')],cwd=str(root),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        ctypes.windll.user32.MessageBoxW(None,'المحرك اتجهز والبرنامج اتفتح. التحديث هيكمل تلقائيًا عند خمول آمن. نجاح تثبيت الإصدار بيتأكد من تقرير الجهاز في الإدارة، مش من الرسالة دي.','تهيئة التحديث التلقائي',0x40)
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None,str(exc),'التهيئة لم تكتمل',0x10)


def diagnose(root=ROOT):
    import ast
    root=Path(root);identity=device_identity(root)
    source=root/'central_updater.py';installed_protocol=None
    if source.is_file():
        try:
            tree=ast.parse(source.read_text(encoding='utf-8-sig'))
            installed_protocol=next((ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='UPDATER_PROTOCOL' for t in n.targets)),1)
        except (ValueError,SyntaxError):installed_protocol='invalid'
    main=(root/'main.py').read_text(encoding='utf-8-sig') if (root/'main.py').is_file() else ''
    return {'diagnostic_tool_protocol':UPDATER_PROTOCOL,'engine_source_present':source.is_file(),
            'installed_engine_protocol':installed_protocol,'standalone_helper_present':(root/'AbuZaidUpdater.exe').is_file(),
            'startup_hook_present':'start_update_service()' in main,
            'branch_id':identity['branch_id'] if identity else None,'approved_identity_available':bool(identity),
            'trusted_keys_available':bool(read_json(root/'update_public_keys.json')),
            'automatic':automatic_policy(root),'installed_metadata_present':(root/'APP_VERSION.json').is_file(),'installed':version_info(root),
            'runtime':read_json(root/'.updates/runtime.json'),'result':read_json(root/'.updates/result.json')}


def _explicit_exit_ticket(root=ROOT):
    """A user's close may finish an update, but must not reopen their POS."""
    import builtins
    value=getattr(builtins,'_abuzaid_update_exit_ticket',None)
    if not value:return
    path=Path(value)
    if path.parent.resolve()!=(Path(root)/'.updates').resolve() or not path.name.startswith('exit-'+str(os.getpid())+'-'):
        raise ValueError('Unexpected update exit ticket')
    ticket=read_json(path)
    if ticket.get('pid')!=os.getpid() or ticket.get('action') not in ('apply','rollback'):
        raise ValueError('Invalid update exit ticket')
    ticket['restart']=False
    atomic_json(path,ticket)


def request_program_exit(root=ROOT):
    """Explicit program close; logout never calls this function."""
    import builtins
    from streamlit.runtime import Runtime
    runtime=Runtime.instance()
    for info in runtime._session_mgr.list_sessions():
        state=info.session.session_state
        flags=('_sale_in_progress','_update_operation_in_progress') if virtual_pos_state(state) else ('cart','pos_success_pending','_sale_in_progress','_sale_draft_save_failed','_update_operation_in_progress')
        for key in flags:
            try:
                if state[key]:raise ValueError('توجد عملية أو سلة بيع مفتوحة؛ أكملها أولاً. لم يُغلق البرنامج.')
            except KeyError:pass
    if draft_pending(root):raise ValueError('توجد مسودة بيع محفوظة؛ استكملها أو أفرغها صراحةً قبل إغلاق البرنامج.')
    current=getattr(builtins,'_abuzaid_explicit_exit_thread',None)
    if current is not None and current.is_alive():return
    _explicit_exit_ticket(root)
    builtins._abuzaid_program_exit_requested=True
    def close_when_safe():
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            try:
                if try_idle_shutdown(root,runtime,explicit=True):return
            except Exception as exc:_STATUS['shutdown_error_type']=type(exc).__name__
            time.sleep(0.2)
        builtins._abuzaid_program_exit_requested=False
        _STATUS['idle_blocked_by']='active_operation_prevented_exit'
    current=threading.Thread(target=close_when_safe,name='abuzaid-explicit-exit',daemon=True)
    builtins._abuzaid_explicit_exit_thread=current;current.start()


def request_safe_exit():
    request_program_exit(ROOT)


def reject_duplicate_program(root):
    """The original per-install lock is held by another instance; close only this new EXE."""
    if (os.name!='nt' or not getattr(sys,'frozen',False)
            or Path(sys.executable).resolve()!=Path(root).resolve()/'AbuZaidPOS.exe'):return False
    # This runs before database imports/login/synchronization in the second process.
    # Never stop or alter the original process that owns the lock.
    os._exit(0)
    return True


def safe_diagnostic(value):
    if not isinstance(value,dict):return {}
    result={}
    for key in ('phase','error_type','error_code'):
        item=value.get(key)
        if isinstance(item,str) and re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,79}',item):result[key]=item
    for key in ('at','http_status','error_errno','error_winerror','error_line'):
        item=value.get(key)
        if type(item) is int and 0<=item<=2**53:result[key]=item
    item=value.get('error_file')
    if isinstance(item,str) and len(item)<=100 and allowed_file(item):result['error_file']=item
    return result


def valid_diagnostic_event(event):
    if not isinstance(event,dict) or set(event)-{'event_id','source','diagnostic'}:return False
    value=event.get('diagnostic')
    return (event.get('source') in ('update','sync','runtime')
        and isinstance(value,dict) and value==safe_diagnostic(value)
        and isinstance(event.get('event_id'),str)
        and event['event_id']==hashlib.sha256(json.dumps(
            {'source':event['source'],'diagnostic':value},sort_keys=True,separators=(',',':')).encode()).hexdigest())


def diagnostic_outbox(root):
    try:
        value=read_json(Path(root)/'.updates/diagnostic-outbox.json')
        if not isinstance(value,dict) or not isinstance(value.get('events',[]),list):raise ValueError('Invalid diagnostic queue')
        value['dropped_events']=max(0,int(value.get('dropped_events',0)))
        return value
    except (OSError,ValueError,TypeError):
        return {'events':[],'dropped_events':0,'diagnostic_queue_rebuilt':True}


def queue_diagnostic(root,source,diagnostic):
    """Persistent metadata only. Reuse the existing periodic update reporter."""
    if source not in ('update','sync','runtime'):return
    value=safe_diagnostic(diagnostic)
    event={'source':source,'diagnostic':value}
    event['event_id']=hashlib.sha256(json.dumps(event,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    path=Path(root)/'.updates/diagnostic-outbox.json'
    with _DIAGNOSTIC_LOCK:
        lock=lock_file(Path(root)/'.updates/diagnostic-outbox.lock',timeout=0.2)
        try:
            current=diagnostic_outbox(root);events=[e for e in current.get('events',[]) if valid_diagnostic_event(e)]
            if not any(e['event_id']==event['event_id'] for e in events):events.append(event)
            dropped=int(current.get('dropped_events',0))+max(0,len(events)-1024)
            atomic_json(path,dict(events=events[-1024:],dropped_events=dropped))
        finally:lock.close()


def acknowledge_diagnostics(root,accepted):
    if not isinstance(accepted,list):return
    accepted={e for e in accepted if isinstance(e,str) and re.fullmatch(r'[a-f0-9]{64}',e)}
    path=Path(root)/'.updates/diagnostic-outbox.json'
    with _DIAGNOSTIC_LOCK:
        lock=lock_file(Path(root)/'.updates/diagnostic-outbox.lock',timeout=0.2)
        try:
            current=diagnostic_outbox(root)
            current['events']=[e for e in current.get('events',[]) if e.get('event_id') not in accepted]
            atomic_json(path,current)
        finally:lock.close()


def record_sync_diagnostic(phase,error_type):
    """Shared safe telemetry; no business retries or financial state changes."""
    try:
        queue_diagnostic(ROOT,'sync',dict(phase=phase,error_type=error_type,
            error_code='sync_stage_failed',at=int(time.time())))
    except (OSError,ValueError,TimeoutError):pass


def _record_update_error(root, exc):
    # No free-form exception strings, request headers, response bodies or URLs.
    messages={
        'Package inventory differs from signed manifest':'inventory_mismatch',
        'File integrity check failed':'file_digest_mismatch',
        'Package digest differs':'package_digest_mismatch',
        'Incomplete update download':'download_digest_mismatch',
        'Invalid archive entry':'invalid_archive_entry',
        'Untrusted update signature':'signature_rejected',
        'Signed independent update host descriptor is missing':'worker_descriptor_missing',
        'Independent update host integrity failed':'worker_digest_mismatch',
        'Runtime integrity check failed':'runtime_digest_mismatch',
    }
    # Matching exact known literals is safe; unknown text is never persisted.
    code=messages.get(str(exc),'')
    if not code:
        code=('python_syntax_rejected' if isinstance(exc,SyntaxError) else
              'access_denied' if isinstance(exc,PermissionError) else
              'file_missing' if isinstance(exc,FileNotFoundError) else
              'invalid_zip' if isinstance(exc,zipfile.BadZipFile) else
              'transport_failed' if isinstance(exc,urllib.error.URLError) else
              'validation_rejected' if isinstance(exc,ValueError) else 'update_failed')
    diagnostic=safe_diagnostic(dict(error_type=type(exc).__name__,
        http_status=getattr(exc,'code',None),phase=_STATUS.get('phase','check'),
        error_code=code,error_errno=getattr(exc,'errno',None),
        error_winerror=getattr(exc,'winerror',None),error_line=getattr(exc,'lineno',None),
        error_file=_STATUS.get('diagnostic_file'),at=int(time.time())))
    _STATUS.update(state='offline_or_rejected',**diagnostic)
    try:atomic_json(Path(root)/'.updates/last-check-error.json',diagnostic)
    except OSError:pass
    try:queue_diagnostic(root,'update',diagnostic)
    except (OSError,ValueError,TimeoutError):pass


def request_login_update_check():
    import builtins
    if not getattr(builtins,'_abuzaid_login_update_requested',False):
        builtins._abuzaid_login_update_requested=True
        request_update_check()


def request_logout_update_check():
    import builtins
    builtins._abuzaid_login_update_requested=False
    request_update_check()


def restore_scheduled_status(root=ROOT):
    """A second check cannot erase a verified pending worker action."""
    global _SCHEDULED
    if not _SCHEDULED:return False
    import builtins
    process=getattr(builtins,'_abuzaid_update_worker_process',None)
    if process is not None and process.poll() is not None:
        _SCHEDULED=False
        lifecycle=getattr(builtins,'_abuzaid_update_lifecycle',None)
        if lifecycle:lifecycle['worker_globals']['_SCHEDULED']=False
        _STATUS.update(state='waiting',idle_blocked_by='worker_wait_ended')
        return False
    ticket=read_json(Path(getattr(builtins,'_abuzaid_update_exit_ticket','')))
    if ticket.get('pid')!=os.getpid() or ticket.get('action') not in ('apply','rollback'):return False
    if _STATUS.get('state') not in ('restarting_for_update','shutdown_waiting_for_safe_exit'):
        _STATUS.update(state='rollback_after_exit' if ticket['action']=='rollback' else 'ready_after_exit')
    return True


def request_update_check(root=ROOT):
    """A manual UI request uses the same serialized, signed background engine."""
    import builtins
    running=getattr(builtins,'_abuzaid_manual_update_check',None)
    if running is not None and running.is_alive():return False
    builtins._abuzaid_manual_update_apply=True
    if restore_scheduled_status(root):return True
    _STATUS.update(state='checking_updates')
    def check():
        try:check_and_stage(root)
        except Exception as exc:_record_update_error(root,exc)
        finally:
            if not _SCHEDULED:builtins._abuzaid_manual_update_apply=False
        try:report_status(root)
        except Exception:pass
    thread=threading.Thread(target=check,name='abuzaid-manual-update-check',daemon=True)
    builtins._abuzaid_manual_update_check=thread;thread.start()
    return True


def show_update_status(role):
    import streamlit as st
    info=status();installed=version_info(ROOT)

    if not role:return
    st.sidebar.markdown('''<style>
    .st-key-central_update_action button{background:#1e293b!important;color:#f8fafc!important}
    .st-key-central_update_action button p{color:#f8fafc!important}
    .st-key-central_update_diagnostics{background:#1e293b;color:#f8fafc}
    .st-key-central_update_diagnostics summary{background:#1e293b!important;color:#f8fafc!important}
    .st-key-central_update_diagnostics summary p,
    .st-key-central_update_diagnostics [data-testid="stCaptionContainer"],
    .st-key-central_update_diagnostics [data-testid="stCaptionContainer"] p{color:#f8fafc!important}
    </style>''',unsafe_allow_html=True)
    if st.sidebar.button('حدّث الآن',key='central_update_action'):
        request_update_check()
    def progress():
        current=version_info(ROOT);value=status();available=value.get('available_release_seq')
        state=value['state']
        from release_info import status_text
        label,message=status_text(current,confirmed_current(value,ROOT),state,available)
        st.caption(label)
        st.caption(message)
        receipt=read_json(ROOT/'.updates/result.json');ack=read_json(ROOT/'.updates/report-ack.json')
        identity=device_identity(ROOT);good=read_json(ROOT/'.updates/last_good.json')
        if (receipt.get('state')=='installed' and receipt.get('release_seq')==current.get('release_seq')
                and identity and ack.get('release_seq')==current.get('release_seq')
                and ack.get('device_id')==identity['device_id'] and ack.get('audit_id')==good.get('audit_id')):
            st.caption('اكتمل تثبيت التحديث وإعادة التشغيل وتأكيد الاستلام.')
    with st.sidebar:
        if hasattr(st,'fragment'):st.fragment(run_every=3)(progress)()
        else:progress()
    if role!='Super_Admin':return
    with st.sidebar.expander('تفاصيل التحديث للإدارة',key='central_update_diagnostics'):
        value=status();current=version_info(ROOT);available=value.get('available_release_seq')
        st.caption('التسلسل المثبت: '+str(current.get('release_seq',0)))
        st.caption('آخر تسلسل متاح من السيرفر: '+(str(available) if type(available) is int else 'لم يُتحقق منه بعد'))
        if value.get('state')=='offline_or_rejected':
            diagnostic=value if value.get('reason') else read_json(ROOT/'.updates/last-check-error.json')
            st.caption('سبب آخر فشل: '+str(diagnostic.get('reason') or 'لم تُسجل تفاصيل؛ أعد الفحص'))
            st.caption('المرحلة: '+str(diagnostic.get('phase') or 'غير معروفة')+' | النوع: '+str(diagnostic.get('error_type') or '')+' | HTTP: '+str(diagnostic.get('http_status') or '—'))
        if (ROOT/'.updates/last_good.json').is_file():
            if st.button('الرجوع لملفات الإصدار السابق بعد الإغلاق',key='update_rollback'):
                try:request_rollback();st.success('الرجوع جاهز بعد إغلاق البرنامج بأمان؛ البيانات محفوظة.')
                except (ValueError,OSError) as exc:st.error(str(exc))
        if st.button('عرض إصدارات أجهزة الفروع',key='update_fleet'):
            try:
                from offline_store import _request_with_auth_retry
                response=_request_with_auth_retry('GET','/admin/updates',timeout=8);response.raise_for_status();rows=response.json()['devices']
                if not isinstance(rows,list):raise ValueError('Invalid fleet status')
                columns=('branch_id','device_id','version','release_seq','state','result','reported_at')
                st.dataframe([{k:row.get(k) for k in columns} for row in rows],hide_index=True)
            except Exception:st.info('تعذر تحميل إيصالات تحديث الأجهزة حالياً.')


if __name__ == "__main__":
    if sys.argv[1:] and sys.argv[1] in ('--apply-after-exit','--rollback-after-exit','--launch') and delegate_trusted_runtime():
        raise SystemExit(0)
    if getattr(sys,'frozen',False) and len(sys.argv)==1:
        interactive_bootstrap()
    elif sys.argv[1:] == ['--self-check']:
        import ssl,sqlite3
        print(json.dumps({'updater_ready':True,'runtime':'.'.join(map(str,sys.version_info[:3])),
                          'bootstrap_version':BASE_VERSION,'updater_protocol':UPDATER_PROTOCOL,'application_started':False,'database_compatibility_guard':True}))
    elif len(sys.argv)==5 and sys.argv[1]=='--bootstrap' and sys.argv[3]=='--expected-device':
        bootstrap_existing_install(Path(sys.argv[2]),sys.argv[4])
    elif len(sys.argv)==3 and sys.argv[1]=='--diagnose':
        print(json.dumps(diagnose(Path(sys.argv[2]))))
    elif sys.argv[1:] == ["--launch"]:
        launch_supervised()
    elif len(sys.argv) == 4 and sys.argv[1] in ("--apply-after-exit", "--rollback-after-exit"):
        try:
            worker(int(sys.argv[2]), sys.argv[3], action="rollback" if sys.argv[1] == "--rollback-after-exit" else "apply")
        except Exception as exc:
            atomic_json(ROOT / ".updates" / "worker_error.json",
                        {"error_type": type(exc).__name__, "time": int(time.time())})
