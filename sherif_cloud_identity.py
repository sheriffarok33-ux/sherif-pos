"""PostgreSQL tenant identity storage; no schema is installed automatically.

Not connected to the UI: deployment and authentication controls require a
real isolated PostgreSQL integration test before activation.
"""
import uuid
from sherif_local_identity import password_hash, password_matches

SCHEMA = """
CREATE TABLE IF NOT EXISTS sherif_organizations (
    id UUID PRIMARY KEY, name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    business_type TEXT NOT NULL DEFAULT '', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sherif_branches (
    id UUID PRIMARY KEY, organization_id UUID NOT NULL REFERENCES sherif_organizations(id),
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120), active BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE (organization_id, id), UNIQUE (organization_id, name)
);
CREATE TABLE IF NOT EXISTS sherif_users (
    id UUID PRIMARY KEY, organization_id UUID NOT NULL REFERENCES sherif_organizations(id),
    branch_id UUID NOT NULL, username TEXT NOT NULL CHECK (length(username) BETWEEN 1 AND 100),
    password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN
      ('Super_Admin', 'Admin', 'Manager', 'Supervisor', 'Cashier')),
    active BOOLEAN NOT NULL DEFAULT TRUE, UNIQUE (organization_id, username), UNIQUE (organization_id, id),
    FOREIGN KEY (organization_id, branch_id) REFERENCES sherif_branches(organization_id, id)
);
CREATE TABLE IF NOT EXISTS sherif_permissions (
    organization_id UUID NOT NULL, user_id UUID NOT NULL,
    permission TEXT NOT NULL CHECK (length(permission) BETWEEN 1 AND 100),
    PRIMARY KEY (organization_id, user_id, permission),
    FOREIGN KEY (organization_id, user_id) REFERENCES sherif_users(organization_id, id)
);
"""


def _clean(value, limit):
    value = str(value or '').strip()
    if not value or len(value) > limit:
        raise ValueError('Invalid identity field')
    return value


def install_schema(connection):
    """Install missing tables atomically; requires an explicitly supplied connection."""
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(SCHEMA)


def provision_organization(connection, name, activity, branch, username, pin):
    """Create one organization, branch and administrator in one transaction."""
    name, branch, username = _clean(name, 120), _clean(branch, 120), _clean(username, 100)
    activity = str(activity or '').strip()
    if len(activity) > 120:
        raise ValueError('Invalid activity')
    hashed = password_hash(pin)
    org_id, branch_id, user_id = (str(uuid.uuid4()) for _ in range(3))
    with connection:
        with connection.cursor() as cursor:
            cursor.execute('INSERT INTO sherif_organizations (id,name,business_type) VALUES (%s,%s,%s)', (org_id,name,activity))
            cursor.execute('INSERT INTO sherif_branches (id,organization_id,name) VALUES (%s,%s,%s)', (branch_id,org_id,branch))
            cursor.execute('INSERT INTO sherif_users (id,organization_id,branch_id,username,password_hash,role) VALUES (%s,%s,%s,%s,%s,%s)', (user_id,org_id,branch_id,username,hashed,'Super_Admin'))
    return {'organization_id': org_id, 'branch_id': branch_id, 'user_id': user_id}


def authenticate(connection, organization_id, username, pin):
    """Resolve a user only inside an explicit organization and active branch."""
    try:
        organization_id = str(uuid.UUID(str(organization_id)))
        username = _clean(username, 100)
    except (ValueError, TypeError, AttributeError):
        return None
    with connection:
        with connection.cursor() as cursor:
            cursor.execute("""SELECT u.id, u.username, u.password_hash, u.role, u.branch_id
              FROM sherif_users u JOIN sherif_branches b
              ON b.id=u.branch_id AND b.organization_id=u.organization_id
              WHERE u.organization_id=%s AND u.username=%s AND u.active AND b.active""",
              (organization_id, username))
            row = cursor.fetchone()
    if not row or not password_matches(pin, row[2]):
        return None
    return {'id': str(row[0]), 'username': row[1], 'role': row[3],
            'branch_id': str(row[4]), 'organization_id': organization_id}
