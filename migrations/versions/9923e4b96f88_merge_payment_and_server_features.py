"""merge payment and server features

Revision ID: 9923e4b96f88
Revises: 20250613_external_url, 3b4940f3dd4b
Create Date: 2025-06-13 23:28:20.629815

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9923e4b96f88'
down_revision = ('20250613_external_url', '3b4940f3dd4b')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
