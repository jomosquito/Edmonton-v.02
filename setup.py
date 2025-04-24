import os
import sys
from datetime import datetime
from main import db, Role, WorkflowConfig, WorkflowStep, app

def setup_roles():
    """Initialize standard roles if they don't exist yet"""
    print("Setting up roles...")

    # Define standard roles
    standard_roles = [
        {"name": "student", "level": 1, "description": "Normal basic user role"},
        {"name": "department_chair", "level": 2, "description": "Can approve any form but not view form history"},
        {"name": "president", "level": 3, "description": "Access to approve any form and view form history"},
        {"name": "admin", "level": 4, "description": "Has access to the whole entire admin portal"}
    ]

    created = 0
    for role_data in standard_roles:
        existing_role = Role.query.filter_by(name=role_data["name"]).first()
        if not existing_role:
            new_role = Role(name=role_data["name"], level=role_data["level"])
            db.session.add(new_role)
            created += 1
            print(f"Created role: {role_data['name']} (level {role_data['level']})")

    db.session.commit()
    print(f"Role setup complete. Created {created} new roles.")

def setup_workflow_configs():
    """Initialize workflow configurations for each form type"""
    print("Setting up workflow configurations...")

    form_types = ['medical_withdrawal', 'student_drop', 'ferpa', 'info_change']
    created = 0

    for form_type in form_types:
        existing_config = WorkflowConfig.query.filter_by(form_type=form_type).first()
        if not existing_config:
            new_config = WorkflowConfig(
                form_type=form_type,
                required_approvers=2,  # Default to 2 required approvers
                updated_at=datetime.utcnow()
            )
            db.session.add(new_config)
            created += 1
            print(f"Created workflow config for: {form_type}")

    db.session.commit()
    print(f"Workflow configuration setup complete. Created {created} new configs.")

def setup_default_workflow_steps():
    """Initialize default workflow steps for each form type"""
    print("Setting up default workflow steps...")

    # Get roles
    department_chair_role = Role.query.filter_by(name="department_chair").first()
    president_role = Role.query.filter_by(name="president").first()

    if not department_chair_role or not president_role:
        print("Error: Required roles not found. Run setup_roles first.")
        return

    form_types = ['medical_withdrawal', 'student_drop', 'ferpa', 'info_change']
    created = 0

    for form_type in form_types:
        # Check if any steps exist for this form type
        existing_steps = WorkflowStep.query.filter_by(form_type=form_type).count()

        if existing_steps == 0:
            # Create default 2-step workflow: department_chair -> president
            step1 = WorkflowStep(
                form_type=form_type,
                step_order=1,
                role_id=department_chair_role.id,
                user_id=None
            )

            step2 = WorkflowStep(
                form_type=form_type,
                step_order=2,
                role_id=president_role.id,
                user_id=None
            )

            db.session.add(step1)
            db.session.add(step2)
            created += 2
            print(f"Created default workflow steps for: {form_type}")

    db.session.commit()
    print(f"Default workflow setup complete. Created {created} new workflow steps.")

if __name__ == "__main__":
    with app.app_context():
        setup_roles()
        setup_workflow_configs()
        setup_default_workflow_steps()