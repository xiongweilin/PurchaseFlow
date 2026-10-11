"""fence outbox worker observations by lease generation

Revision ID: 4a10b93f76d2
Revises: 2e4c21c85276
Create Date: 2026-10-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "4a10b93f76d2"
down_revision = "2e4c21c85276"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "outbox_events",
        sa.Column("lease_generation", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("outbox_events", "lease_generation")
