"""Create experiment run metadata table."""
from alembic import op
import sqlalchemy as sa

revision = "0001_experiment_runs"
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "experiment_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("result_type", sa.String(length=24), nullable=False),
        sa.Column("workload_metadata", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("result_path", sa.Text(), nullable=False),
    )

def downgrade() -> None:
    op.drop_table("experiment_runs")
