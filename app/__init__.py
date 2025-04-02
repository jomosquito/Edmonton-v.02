from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from config import client_id, client_secret, SECRET_KEY
import os
import json

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = SECRET_KEY
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
    app.config['UPLOAD_FOLDER'] = 'static/uploads'
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
    
    db.init_app(app)
    
    # Register blueprints
    from app.routes.auth_routes import auth_bp
    from app.routes.admin_routes import admin_bp
    from app.routes.medical_routes import medical_bp
    from app.routes.student_routes import student_bp
    from app.routes.main_routes import main_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(medical_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(main_bp)
    
    # Create upload directories
    with app.app_context():
        from app.models import MyDB  # Import your models
        os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'documentation'), exist_ok=True)
        os.makedirs(os.path.join('static', 'pdfs'), exist_ok=True)
        os.makedirs(os.path.join('static', 'temp'), exist_ok=True)
        
        # Custom filter for JSON parsing
        @app.template_filter('from_json')
        def from_json(value):
            return json.loads(value) if value else []
    
    return app