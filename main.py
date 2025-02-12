from flask import Flask, render_template, url_for
from flask_sqlalchemy import SQLAlchemy
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
db = SQLAlchemy(app)
class profile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.String(200), nullable=False)

    def __repr__(self):
        return '<Task %r>' % self.id
@app.route('/')
def index():
    return render_template('index.html') #acceses index.html file gi

if __name__ == "__main__":
    with app.app_context():
        db.create_all()  
    app.run(debug=True)
