"""Ensure agent_personas.persona_name is uniquely constrained.

Revision ID: 002
Revises: 001
Create Date: 2026-03-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_index idx
                    JOIN pg_class tbl ON tbl.oid = idx.indrelid
                    JOIN pg_attribute attr
                      ON attr.attrelid = tbl.oid
                     AND attr.attnum = ANY(idx.indkey)
                    WHERE tbl.relname = 'agent_personas'
                      AND idx.indisunique
                      AND attr.attname = 'persona_name'
                ) THEN
                    ALTER TABLE agent_personas
                    ADD CONSTRAINT uq_agent_personas_persona_name UNIQUE (persona_name);
                END IF;
            END $$;
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            ALTER TABLE agent_personas
            DROP CONSTRAINT IF EXISTS uq_agent_personas_persona_name;
            """
        )
    )
