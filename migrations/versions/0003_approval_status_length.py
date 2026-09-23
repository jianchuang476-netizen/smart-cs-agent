"""Widen approval status values.

Revision ID: 0003_approval_status_length
Revises: 0002_approval_feedback
Create Date: 2026-09-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_approval_status_length"
down_revision = "0002_approval_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "approvals",
        "status",
        existing_type=sa.String(length=8),
        type_=sa.String(length=30),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "approvals",
        "status",
        existing_type=sa.String(length=30),
        type_=sa.String(length=8),
        existing_nullable=False,
    )
