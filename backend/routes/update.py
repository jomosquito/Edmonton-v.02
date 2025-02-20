from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)

# Mock data for demonstration
profiles = [
    {"id": 1, "email_": "user1@example.com", "first_name": "John", "privilages_": "user", "active": True},
    {"id": 2, "email_": "user2@example.com", "first_name": "Jane", "privilages_": "admin", "active": False},
]

@app.route("/")
def index():
    return render_template("index.html", profiles=profiles)

@app.route("/update/<int:id>", methods=["GET", "POST"])
def update_profile(id):
    profile = next((p for p in profiles if p["id"] == id), None)
    if not profile:
        return "Profile not found", 404

    if request.method == "POST":
        # Update profile data from the form
        profile["email_"] = request.form.get("email")
        profile["first_name"] = request.form.get("username")
        profile["privilages_"] = request.form.get("privileges")
        profile["active"] = request.form.get("active") == "on"
        return redirect(url_for("index"))

    return render_template("update.html", profile=profile)

if __name__ == "__main__":
    app.run(debug=True)
