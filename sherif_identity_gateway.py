"""Common identity operations with explicitly selected, caller-owned storage.

This adapter is not wired into the production UI. PostgreSQL integration and
online authentication protections must be verified before activation.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SetupData:
    company: str
    activity: str
    branch: str
    device: str
    username: str
    pin: str


class IdentityGateway:
    def __init__(self, connection, backend, organization_id=None):
        if backend not in ('sqlite', 'postgresql'):
            raise ValueError('Unsupported identity storage')
        if backend == 'sqlite' and organization_id is not None:
            raise ValueError('A local identity does not accept an organization identifier')
        if backend == 'postgresql' and not organization_id:
            raise ValueError('Cloud identity requires an explicit organization identifier')
        self.connection = connection
        self.backend = backend
        self.organization_id = organization_id

    def authenticate(self, username, pin):
        if self.backend == 'sqlite':
            from sherif_local_identity import authenticate
            return authenticate(self.connection, username, pin)
        from sherif_cloud_identity import authenticate
        return authenticate(self.connection, self.organization_id, username, pin)


def provision_identity(connection, backend, data: SetupData):
    """Create identity in the explicitly selected store; never opens a connection."""
    if not isinstance(data, SetupData):
        raise TypeError('Expected SetupData')
    if backend == 'sqlite':
        from sherif_local_identity import provision_fresh
        return provision_fresh(connection, data.company, data.branch, data.device,
                               data.username, data.pin, data.activity)
    if backend == 'postgresql':
        from sherif_cloud_identity import provision_organization
        if not str(data.device or '').strip() or len(str(data.device).strip()) > 120:
            raise ValueError('Invalid device name')
        # Cloud device registration is a separate operation, not yet implemented.
        return provision_organization(connection, data.company, data.activity,
                                      data.branch, data.username, data.pin)
    raise ValueError('Unsupported identity storage')
