#This migration code is to update the database schema
#Made by Niket Gupta

from main import db, app, MedicalWithdrawalRequest, StudentInitiatedDrop
import sqlalchemy as sa
import os

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

# Add FERPARequest and InfoChangeRequest tables to migrations
with app.app_context():
    # Create all tables if they don't exist
    db.create_all()

    # Check if FERPARequest table has admin_viewed column
    with db.engine.connect() as conn:
        inspector = sa.inspect(db.engine)

         # Add admin_viewed column to FERPARequest if it doesn't exist
        columns = inspector.get_columns('ferpa_request')
        if 'admin_viewed' not in [col['name'] for col in columns]:
            conn.execute(sa.text('ALTER TABLE ferpa_request ADD COLUMN admin_viewed TEXT'))

        # Add admin_viewed column to InfoChangeRequest if it doesn't exist
        columns = inspector.get_columns('info_change_request')
        if 'admin_viewed' not in [col['name'] for col in columns]:
            conn.execute(sa.text('ALTER TABLE info_change_request ADD COLUMN admin_viewed TEXT'))

        # Check FERPARequest table
        tables = inspector.get_table_names()
        if 'ferpa_request' in tables:
            columns = inspector.get_columns('ferpa_request')
            if 'admin_viewed' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE ferpa_request ADD COLUMN admin_viewed TEXT'))

        # Check InfoChangeRequest table
        if 'info_change_request' in tables:
            columns = inspector.get_columns('info_change_request')
            if 'admin_viewed' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE info_change_request ADD COLUMN admin_viewed TEXT'))

        # Original migrations for other tables
        if 'medical_withdrawal_request' in tables:
            columns = inspector.get_columns('medical_withdrawal_request')
            if 'admin_viewed' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE medical_withdrawal_request ADD COLUMN admin_viewed TEXT'))

        if 'student_initiated_drop' in tables:
            columns = inspector.get_columns('student_initiated_drop')
            if 'generated_pdfs' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE student_initiated_drop ADD COLUMN generated_pdfs TEXT'))
            if 'admin_viewed' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE student_initiated_drop ADD COLUMN admin_viewed TEXT'))

    db.session.commit()

# Add admin_approvals columns if they don't exist
with app.app_context():
    with db.engine.connect() as conn:
        inspector = sa.inspect(db.engine)
        
        # Check for admin_approvals in all request tables
        tables = inspector.get_table_names()
        
        if 'medical_withdrawal_request' in tables:
            columns = inspector.get_columns('medical_withdrawal_request')
            if 'admin_approvals' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE medical_withdrawal_request ADD COLUMN admin_approvals TEXT'))
        
        if 'student_initiated_drop' in tables:
            columns = inspector.get_columns('student_initiated_drop')
            if 'admin_approvals' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE student_initiated_drop ADD COLUMN admin_approvals TEXT'))
        
        if 'ferpa_request' in tables:
            columns = inspector.get_columns('ferpa_request')
            if 'admin_approvals' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE ferpa_request ADD COLUMN admin_approvals TEXT'))
        
        if 'info_change_request' in tables:
            columns = inspector.get_columns('info_change_request')
            if 'admin_approvals' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE info_change_request ADD COLUMN admin_approvals TEXT'))

    db.session.commit()

# Add org_unit_id and active columns to departments table if they don't exist
with app.app_context():
    with db.engine.connect() as conn:
        inspector = sa.inspect(db.engine)
        
        # Check for org_unit_id in departments table
        tables = inspector.get_table_names()
        
        if 'departments' in tables:
            columns = inspector.get_columns('departments')
            if 'org_unit_id' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE departments ADD COLUMN org_unit_id INTEGER REFERENCES organizational_units(id)'))
                print("Added org_unit_id column to departments table")
            
            # Check for active column in departments table
            if 'active' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE departments ADD COLUMN active BOOLEAN DEFAULT TRUE'))
                print("Added active column to departments table")

    db.session.commit()

# Add created_at column to departments table if it doesn't exist
with app.app_context():
    with db.engine.connect() as conn:
        inspector = sa.inspect(db.engine)
        
        # Check for created_at in departments table
        tables = inspector.get_table_names()
        
        if 'departments' in tables:
            columns = inspector.get_columns('departments')
            if 'created_at' not in [col['name'] for col in columns]:
                conn.execute(sa.text('ALTER TABLE departments ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'))
                print("Added created_at column to departments table")

    db.session.commit()
    print("Migrations completed successfully!")