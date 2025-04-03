#This migration code is to update the database schema
#Made by Niket Gupta

from main import db, app, MedicalWithdrawalRequest, StudentInitiatedDrop
import sqlalchemy as sa

with app.app_context():
    # Create all tables if they don't exist
    db.create_all()
    
    # Add admin_viewed column to MedicalWithdrawalRequest if it doesn't exist
    with db.engine.connect() as conn:
        inspector = sa.inspect(db.engine)
        columns = inspector.get_columns('medical_withdrawal_request')
        if 'admin_viewed' not in [col['name'] for col in columns]:
            conn.execute(sa.text('ALTER TABLE medical_withdrawal_request ADD COLUMN admin_viewed TEXT'))
            
    # Add columns to StudentInitiatedDrop if they don't exist
    with db.engine.connect() as conn:
        inspector = sa.inspect(db.engine)
        columns = inspector.get_columns('student_initiated_drop')
        
        # Check if the table exists
        if 'student_initiated_drop' in inspector.get_table_names():
            if 'generated_pdfs' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE student_initiated_drop ADD COLUMN generated_pdfs TEXT'))
            if 'admin_viewed' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE student_initiated_drop ADD COLUMN admin_viewed TEXT'))
    
    db.session.commit()