import os
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.security import Permission, Role, RoleAssignment, RolePermission

actor = os.getenv('NEXT_PUBLIC_ACTOR_REFERENCE', 'admin-portal')
now = datetime.now(timezone.utc)

with SessionLocal() as db:
    perms = db.scalars(select(Permission).where(Permission.resource == 'control_plane.scheduler')).all()
    required = {p.action: p for p in perms if p.action in {'read', 'administer'}}
    if set(required) != {'read', 'administer'}:
        raise RuntimeError('scheduler permissions are not seeded')

    for org in db.scalars(select(Organization).where(Organization.status == 'active')):
        role = db.scalar(select(Role).where(Role.organization_id == org.id, Role.code == 'local-scheduler-operator'))
        if role is None:
            role = Role(
                organization_id=org.id,
                code='local-scheduler-operator',
                name='Local Scheduler Operator',
                status='active',
                config={'environment': 'local'},
                created_at=now,
                updated_at=now,
                created_by='local-bootstrap',
                updated_by='local-bootstrap',
            )
            db.add(role)
            db.flush()

        for permission in required.values():
            if db.scalar(select(RolePermission.id).where(RolePermission.role_id == role.id, RolePermission.permission_id == permission.id)) is None:
                db.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=permission.id,
                        created_at=now,
                        updated_at=now,
                        created_by='local-bootstrap',
                        updated_by='local-bootstrap',
                    )
                )

        if db.scalar(select(RoleAssignment.id).where(RoleAssignment.organization_id == org.id, RoleAssignment.role_id == role.id, RoleAssignment.principal_id == actor)) is None:
            db.add(
                RoleAssignment(
                    organization_id=org.id,
                    role_id=role.id,
                    principal_type='user',
                    principal_id=actor,
                    scope_type='organization',
                    scope_id=str(org.id),
                    status='active',
                    created_at=now,
                    updated_at=now,
                    created_by='local-bootstrap',
                    updated_by='local-bootstrap',
                )
            )

    db.commit()
    print(f'local scheduler access ready for {actor}')
