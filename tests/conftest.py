from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    Department,
    Membership,
    Organization,
    PolicyConfig,
    ProductMapping,
    SupplierMapping,
    User,
    utcnow,
)


@pytest.fixture
def session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def seeded(session_factory: sessionmaker[Session]) -> dict:
    with session_factory() as db:
        organization = Organization(
            code="demo-office",
            name="Demo Office Ltd.",
            currency_code="CNY",
            odoo_company_id=1,
            odoo_currency_id=6,
        )
        db.add(organization)
        db.flush()
        admin_department = Department(
            organization_id=organization.id,
            code="admin",
            name="行政部",
        )
        operations_department = Department(
            organization_id=organization.id,
            code="operations",
            name="运营部",
        )
        db.add_all([admin_department, operations_department])
        db.flush()

        identities = {
            "requester.admin@demo.local": ("行政部申请人", "requester", admin_department.id),
            "requester.ops@demo.local": ("运营部申请人", "requester", operations_department.id),
            "manager.admin@demo.local": ("行政部负责人", "manager", admin_department.id),
            "manager.ops@demo.local": ("运营部负责人", "manager", operations_department.id),
            "finance.one@demo.local": ("财务复核人甲", "finance", None),
            "finance.two@demo.local": ("财务复核人乙", "finance", None),
            "procurement@demo.local": ("采购管理员", "procurement", None),
            "admin@demo.local": ("演示系统管理员", "admin", None),
            "dual-role@demo.local": ("双角色测试人", "requester", admin_department.id),
        }
        users = {}
        for email, (name, role, department_id) in identities.items():
            user = User(email=email, display_name=name, active=True)
            db.add(user)
            db.flush()
            db.add(
                Membership(
                    organization_id=organization.id,
                    user_id=user.id,
                    role=role,
                    department_id=department_id,
                )
            )
            users[email] = user
        dual = users["dual-role@demo.local"]
        db.add(
            Membership(
                organization_id=organization.id,
                user_id=dual.id,
                role="manager",
                department_id=admin_department.id,
            )
        )

        db.add(
            PolicyConfig(
                organization_id=organization.id,
                version=1,
                manager_limit=Decimal("5000.00"),
                policy_review_limit=Decimal("20000.00"),
                tax_inclusive=True,
            )
        )
        now = utcnow()
        suppliers = [
            SupplierMapping(
                organization_id=organization.id,
                external_ref="PF-VENDOR-OFFICE",
                name="Demo Office Supplies Ltd.",
                odoo_partner_id=6,
                mapping_version=1,
                active=True,
                validated_at=now,
            ),
            SupplierMapping(
                organization_id=organization.id,
                external_ref="PF-VENDOR-IT",
                name="Demo Technology Ltd.",
                odoo_partner_id=7,
                mapping_version=1,
                active=True,
                validated_at=now,
            ),
        ]
        products = [
            ProductMapping(
                organization_id=organization.id,
                sku="PF-OFFICE-SET",
                name="Office supplies set",
                odoo_product_id=1,
                odoo_uom_id=1,
                odoo_tax_id=5,
                unit_price=Decimal("1200.00"),
                tax_rate=Decimal("13.00"),
                currency_code="CNY",
                mapping_version=1,
                active=True,
                validated_at=now,
            ),
            ProductMapping(
                organization_id=organization.id,
                sku="PF-IT-MONITOR",
                name="Business monitor",
                odoo_product_id=2,
                odoo_uom_id=1,
                odoo_tax_id=5,
                unit_price=Decimal("4000.00"),
                tax_rate=Decimal("13.00"),
                currency_code="CNY",
                mapping_version=1,
                active=True,
                validated_at=now,
            ),
            ProductMapping(
                organization_id=organization.id,
                sku="PF-SERVICE-CONSULT",
                name="Business services package",
                odoo_product_id=3,
                odoo_uom_id=1,
                odoo_tax_id=6,
                unit_price=Decimal("5000.00"),
                tax_rate=Decimal("6.00"),
                currency_code="CNY",
                mapping_version=1,
                active=True,
                validated_at=now,
            ),
        ]
        db.add_all([*suppliers, *products])
        db.commit()
        return {
            "organization_id": organization.id,
            "admin_department_id": admin_department.id,
            "operations_department_id": operations_department.id,
            "users": users,
        }


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> TestClient:
    def override_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def authorized_client(client: TestClient, seeded: dict):
    def login(role: str, email: str, department_code: str | None = None) -> dict:
        response = client.post(
            "/api/demo/sessions",
            json={"role": role, "email": email, "department_code": department_code},
        )
        assert response.status_code == 200, response.text
        return response.json()

    return client, login
