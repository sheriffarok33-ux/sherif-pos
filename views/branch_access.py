"""Shared branch authorization; workstation binding is never a user scope."""
import json
ADMIN_ROLES=('Super_Admin','Admin','Manager')

def branch_scope(role,assigned,allowed=None):
    # The existing "all branches" selector stores NULL; do not reinterpret the
    # legacy ALL column default on a branch-bound account as a new global grant.
    if role in ADMIN_ROLES and assigned is None:return None
    ids=set()
    if assigned is not None:ids.add(int(assigned))
    if role in ADMIN_ROLES:
        try:values=json.loads(allowed) if isinstance(allowed,str) else allowed
        except (TypeError,ValueError):values=None
        if isinstance(values,list):
            for value in values:
                if type(value) is int and value>0:ids.add(value)
    return frozenset(ids)

def can_access_branch(user,branch_id):
    if not user or not user.get('is_active',1):return False
    scope=branch_scope(user.get('role'),user.get('branch_id'),user.get('allowed_branches'))
    return scope is None or int(branch_id) in scope

def saved_branch_scope(role,branch_id):
    return 'ALL' if branch_scope(role,branch_id) is None else json.dumps(sorted(branch_scope(role,branch_id)))

def apply_account_scope(conn,profile,server_time):
    """Refresh existing identity metadata from the authenticated TLS snapshot only.

    Caller owns the transaction. Never create an account, alter a password, or
    read a profile from a user-editable preference/session value.
    """
    if profile is None:return False  # Older API snapshots remain compatible.
    if not isinstance(profile,dict) or type(profile.get('id')) is not int or profile['id']<=0:
        raise ValueError('بيانات صلاحيات الحساب غير صالحة')
    required=('username','role','branch_id','is_active','allowed_branches','custom_permissions')
    if any(k not in profile for k in required) or not isinstance(profile['username'],str) or not isinstance(profile['role'],str):
        raise ValueError('بيانات صلاحيات الحساب غير مكتملة')
    if type(server_time) is not int or server_time<=0:raise ValueError('وقت تحديث الصلاحيات غير صالح')
    key='account_scope_time:'+str(profile['id'])
    previous=conn.execute('SELECT value FROM local_meta WHERE key=?',(key,)).fetchone()
    if previous and int(previous[0])>server_time:return False
    row=conn.execute('SELECT username FROM users WHERE id=?',(profile['id'],)).fetchone()
    if row is None:return False  # Enrollment is still the sole identity creator.
    if row[0]!=profile['username']:raise ValueError('هوية الحساب المركزي لا تطابق الحساب المحلي')
    conn.execute('UPDATE users SET role=?,branch_id=?,is_active=?,allowed_branches=?,custom_permissions=? WHERE id=? AND username=?',
        tuple(profile[k] for k in ('role','branch_id','is_active','allowed_branches','custom_permissions','id','username')))
    conn.execute('INSERT OR REPLACE INTO local_meta(key,value) VALUES(?,?)',(key,str(server_time)))
    return True
