"""Offline SHERIF update worker; invoke independently only after closing POS.

No network download and no process termination. Health is a local startup signal;
production release remains disabled until the worker and launcher are packaged/tested.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import central_updater as updater


def run(root, timeout=45):
    root=Path(root).resolve()
    stage=updater.checked_path(root,'.updates/sherif')
    request=updater.read_json(stage/'request.json')
    keys=updater.read_json(root/'update_public_keys.json')
    previous=updater.verify_envelope(request['previous_envelope'],keys)
    candidate=updater.verify_envelope(request['envelope'],keys)
    if type(previous.get('release_seq')) is not int:
        raise ValueError('Signed previous release sequence is required')
    if updater.installed_pos_image_present(root,'pos.exe'):
        raise RuntimeError('SHERIF is still running; update deferred')
    result=updater.install_sherif_candidate(root,stage/'candidate.zip',request['envelope'],
                                            request['previous_envelope'],{'release_seq':previous['release_seq']})
    nonce=secrets.token_hex(16)
    marker=updater.checked_path(root,'.updates/sherif/health-'+nonce+'.json')
    env=dict(os.environ,SHERIF_UPDATE_HEALTH_NONCE=nonce)
    process=None
    try:
        process=subprocess.Popen([str(root/'pos.exe')],cwd=str(root),env=env,
                                 stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if process.poll() is not None: break
            if marker.is_file():
                health=updater.read_json(marker)
                image_hash=hashlib.sha256((root/'pos.exe').read_bytes()).hexdigest()
                if (health.get('nonce')==nonce and health.get('state')=='ready'
                    and (health.get('pid')==process.pid or health.get('parent_pid')==process.pid)
                    and image_hash==updater._sherif_exe_item(candidate)['sha256']):
                    updater.atomic_json(stage/'last-good-envelope.json',request['envelope'])
                    updater.checked_path(root,'.updates/sherif/transaction.json').unlink()
                    marker.unlink(missing_ok=True)
                    return {'state':'installed','release_seq':result['release_seq']}
            time.sleep(.2)
    except Exception:
        # Recovery below is only safe after the launched image is no longer running.
        pass
    if process is not None and process.poll() is None:
        updater.atomic_json(stage/'status.json',{'state':'recovery_waiting_shutdown','release_seq':result['release_seq']})
        # Never terminate a user session: restore automatically once the image closes.
        process.wait()
    updater.recover_sherif_update(root)
    marker.unlink(missing_ok=True)
    return {'state':'rolled_back','release_seq':result['release_seq']}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--timeout',type=float,default=45)
    args=parser.parse_args()
    print(json.dumps(run(args.root,args.timeout),ensure_ascii=False))


if __name__=='__main__':main()
