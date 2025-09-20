from __future__ import annotations

# Initial Alembic revision to stamp current schema managed by SQLAlchemy metadata.create_all.
# Future schema changes should be implemented via Alembic migrations.

from alembic import op  # noqa: F401
import sqlalchemy as sa  # noqa: F401

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # No-op: schema is created elsewhere (SQLAlchemy metadata.create_all)
    pass


def downgrade() -> None:
    # No-op
    pass
