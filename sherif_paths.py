"""Application data locations: packaged installs use a separate writable directory."""
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parent

def data_dir():
    value=os.environ.get('SHERIF_DATA_DIR')
    return Path(value).resolve() if value else ROOT

def local_db():
    if not os.environ.get('SHERIF_DATA_DIR'):
        return data_dir()/'abu_zaid_local.db'
    marker=data_dir()/'local_database.txt'
    if marker.is_file():
        name=marker.read_text(encoding='utf-8').strip()
        if not name or Path(name).name != name or not name.endswith('.db'):
            raise ValueError('Invalid local database binding')
        return data_dir()/name
    return data_dir()/'sherif_local.db'


def reserve_company_db(company):
    import re, uuid
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(company)).strip(' .')[:60].strip(' .') or 'SHERIF'
    if name.upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:
        name='SHERIF_'+name
    for _ in range(5):
        path=data_dir()/(name+'_'+uuid.uuid4().hex[:12]+'_local.db')
        try:
            with path.open('xb'): pass
            return path
        except FileExistsError:
            continue
    raise RuntimeError('تعذر إنشاء اسم قاعدة بيانات فريد.')


def bind_company_db(path):
    marker=data_dir()/'local_database.txt'
    if marker.exists(): raise RuntimeError('يوجد ارتباط سابق بقاعدة بيانات.')
    with marker.open('x',encoding='utf-8') as f:
        f.write(path.name+'\n')


def auth_db():return data_dir()/'branch_auth.db'
def session_db():return data_dir()/'auth_sessions.db'
def backups():return data_dir()/'backups'
