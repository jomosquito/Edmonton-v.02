#imports 
from flask import Flask, render_template, url_for,request,redirect
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
#data setup
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'

db = SQLAlchemy(app)
class profile(db.Model):
    # true means it can not be left blank and false means it can be left blanks
    id = db.Column(db.Integer, primary_key=True) 
    content = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(50), default="basicuser")
    status = db.Column(db.Boolean, default=True) 
    dateofentry = db.Column(db.DateTime, default=datetime.utcnow)

# returns id 
    def __repr__(self):
        return '<Task %r>' % self.id
#routes 
@app.route('/',methods=['POST','GET'])
def index():
    # updating database 
    if  request.method == 'POST':
        task_content = request.form['content']
        new_task = profile(content=task_content)

        try:
            db.session.add(new_task)
            db.session.commit()
            return redirect('/')
        except:
            return " break"
    else:
        tasks = profile.query.order_by(profile.date_created)
        return render_template('index.html') #acceses index.html file

if __name__ == "__main__":
    with app.app_context():
        db.create_all()  
    app.run(debug=True)
