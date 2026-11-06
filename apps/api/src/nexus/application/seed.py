"""Seed command: synthetic reference restaurants and an optional local admin.

Idempotent. The admin user is created only when SEED_ADMIN_EMAIL and
SEED_ADMIN_PASSWORD are provided (no default credentials exist).
Demo visitors never use these restaurants: each demo session gets its own copies.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import select

from nexus.application.audit import Actor, record_audit
from nexus.application.sandbox import create_restaurant_from_template
from nexus.application.security import hash_password
from nexus.config import get_settings
from nexus.domain.catalog import cached_catalog
from nexus.infra.db import session_scope
from nexus.infra.models import Membership, Restaurant, User
from nexus.logging_config import configure_logging

log = logging.getLogger("nexus.seed")


def seed() -> dict[str, int]:
    settings = get_settings()
    catalog = cached_catalog(settings.dataset_dir)
    created_restaurants = 0
    created_users = 0
    with session_scope() as s:
        existing = {r.template_key: r for r in s.scalars(select(Restaurant).where(Restaurant.is_demo.is_(False)))}
        for template in catalog.templates:
            if template.key not in existing:
                restaurant = create_restaurant_from_template(s, template)
                existing[template.key] = restaurant
                created_restaurants += 1
                record_audit(
                    s,
                    restaurant_id=restaurant.id,
                    actor=Actor.system("Seed"),
                    action="restaurant.seeded",
                    target_type="restaurant",
                    target_id=restaurant.id,
                    details={"template": template.key},
                )
            elif existing[template.key].name != template.name:
                # Names follow the catalog, so a rename also reaches restaurants seeded by an older version.
                existing[template.key].name = template.name
        email = os.environ.get("SEED_ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("SEED_ADMIN_PASSWORD", "")
        if email and password:
            if len(password) < 12:
                raise SystemExit("SEED_ADMIN_PASSWORD must have at least 12 characters")
            user = s.scalars(select(User).where(User.email == email)).one_or_none()
            if user is None:
                user = User(email=email, display_name=email.split("@")[0], password_hash=hash_password(password))
                s.add(user)
                s.flush()
                created_users += 1
            for restaurant in existing.values():
                if s.get(Membership, (user.id, restaurant.id)) is None:
                    s.add(Membership(user_id=user.id, restaurant_id=restaurant.id, role="owner"))
    return {"restaurants_created": created_restaurants, "users_created": created_users}


def main() -> None:
    configure_logging(get_settings().log_level)
    result = seed()
    log.info("seed completed", extra=result)
    print(result)


if __name__ == "__main__":
    main()
