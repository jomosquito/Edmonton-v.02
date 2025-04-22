from main import db, app
import sqlalchemy as sa
from datetime import datetime
import sqlite3

print("Starting database fix for departments table...")

with app.app_context():
    try:
        with db.engine.connect() as conn:
            inspector = sa.inspect(db.engine)
            
            # Check if departments table exists
            tables = inspector.get_table_names()
            if 'departments' not in tables:
                print("Departments table does not exist! Creating it...")
                # This should trigger SQLAlchemy to create the table with all columns
                db.create_all()
            else:
                # Check for created_at column
                columns = inspector.get_columns('departments')
                if 'created_at' not in [col['name'] for col in columns]:
                    print("Adding created_at column to departments table...")
                    # Use NULL as default for SQLite compatibility
                    conn.execute(sa.text('ALTER TABLE departments ADD COLUMN created_at TIMESTAMP'))
                    
                    # Update all existing rows with current timestamp
                    current_time = datetime.utcnow().isoformat()
                    conn.execute(sa.text(f"UPDATE departments SET created_at = '{current_time}'"))
                    
                # Check for active column
                if 'active' not in [col['name'] for col in columns]:
                    print("Adding active column to departments table...")
                    conn.execute(sa.text('ALTER TABLE departments ADD COLUMN active BOOLEAN DEFAULT 1'))
                    
                # Check for org_unit_id column
                if 'org_unit_id' not in [col['name'] for col in columns]:
                    print("Adding org_unit_id column to departments table...")
                    conn.execute(sa.text('ALTER TABLE departments ADD COLUMN org_unit_id INTEGER'))
            
            db.session.commit()
        
        print("Database fix completed successfully!")
    except Exception as e:
        print(f"Error occurred: {e}")
        
        # If the above approach doesn't work, try a more drastic approach - recreate the table
        if isinstance(e, sqlite3.OperationalError) or "OperationalError" in str(e):
            print("Attempting alternative fix with table recreation...")
            
            try:
                # This is a more invasive approach but should work for SQLite
                with db.engine.connect() as conn:
                    # Get existing data
                    result = conn.execute(sa.text("SELECT id, name, code FROM departments"))
                    existing_data = result.fetchall()
                    
                    # Create temp table with all needed columns
                    conn.execute(sa.text("""
                    CREATE TABLE departments_new (
                        id INTEGER PRIMARY KEY,
                        name VARCHAR(100) NOT NULL,
                        code VARCHAR(20) NOT NULL UNIQUE,
                        org_unit_id INTEGER,
                        active BOOLEAN DEFAULT 1,
                        created_at TIMESTAMP
                    )
                    """))
                    
                    # Copy data
                    current_time = datetime.utcnow().isoformat()
                    for row in existing_data:
                        conn.execute(sa.text(f"""
                        INSERT INTO departments_new (id, name, code, created_at, active)
                        VALUES ({row[0]}, '{row[1]}', '{row[2]}', '{current_time}', 1)
                        """))
                    
                    # Drop old table and rename new one
                    conn.execute(sa.text("DROP TABLE departments"))
                    conn.execute(sa.text("ALTER TABLE departments_new RENAME TO departments"))
                    
                    db.session.commit()
                    print("Table recreation completed successfully!")
            except Exception as e2:
                print(f"Alternative fix failed: {e2}")
                raise
