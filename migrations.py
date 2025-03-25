#This migration code is to update the database schema
#Made by Niket Gupta

from main import db, app, MedicalWithdrawalRequest
import sqlalchemy as sa

with app.app_context():
    # Add admin_viewed column if it doesn't exist
    with db.engine.connect() as conn:
        inspector = sa.inspect(db.engine)
        columns = inspector.get_columns('medical_withdrawal_request')
        if 'admin_viewed' not in [col['name'] for col in columns]:
            conn.execute(sa.text('ALTER TABLE medical_withdrawal_request ADD COLUMN admin_viewed TEXT'))
    db.session.commit()