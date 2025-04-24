from main import app, db, WorkflowConfig

def setup_workflow_config():
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Initialize default workflow configs if they don't exist
        default_configs = [
            ('medical_withdrawal', 1),
            ('student_drop', 1),
            ('ferpa', 1),
            ('info_change', 1)
        ]
        
        for form_type, approvers in default_configs:
            if not WorkflowConfig.query.filter_by(form_type=form_type).first():
                config = WorkflowConfig(form_type=form_type, required_approvers=approvers)
                db.session.add(config)
        
        db.session.commit()
        print("Workflow configuration setup complete!")

if __name__ == '__main__':
    setup_workflow_config()