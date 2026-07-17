"""One-off script to seed/update an AdminUser row with a bcrypt password hash.

Usage (via Railway, so DATABASE_URL points at the live production DB):
    railway run python scripts/seed_admin.py <email> <password> [tenant_id]

Not wired into any router — there's intentionally no create-admin endpoint yet.
This is a direct DB seed, mirroring how admin@demo-college.test was created.
"""

import sys
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, ".")

from app.credentials.generation import hash_password  # noqa: E402
from app.db.session import DATABASE_URL  # noqa: E402
from app.models.core import AdminUser, Tenant  # noqa: E402


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: seed_admin.py <email> <password> [tenant_id]")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]
    tenant_id_arg = sys.argv[3] if len(sys.argv) > 3 else None

    engine = create_engine(DATABASE_URL)
    with Session(engine) as db:
        if tenant_id_arg:
            tenant_id = uuid.UUID(tenant_id_arg)
            tenant = db.get(Tenant, tenant_id)
            if tenant is None:
                print(f"No tenant found with id {tenant_id}")
                sys.exit(1)
        else:
            tenant = db.query(Tenant).first()
            if tenant is None:
                print("No tenant rows exist at all — cannot seed an admin without one.")
                sys.exit(1)
            tenant_id = tenant.id

        admin = db.query(AdminUser).filter(AdminUser.email == email).first()
        if admin is None:
            admin = AdminUser(email=email, tenant_id=tenant_id, role="admin")
            db.add(admin)
            action = "created"
        else:
            action = "updated"

        admin.password_hash = hash_password(password)
        db.commit()
        db.refresh(admin)

        print(f"Admin {action}: id={admin.id} email={admin.email} tenant_id={admin.tenant_id}")


if __name__ == "__main__":
    main()
