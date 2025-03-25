# Edmonton

This project is a web application for managing user profiles.

## Setup Instructions

1. **Clone the repository:**

   ```sh
   git clone https://github.com/yourusername/Edmonton.git
   cd Edmonton

2. **Setup Instructions**
   ```sh
   pip install -r requirements.txt

**This command installs**:

**Flask**: The web framework.

**flask_sqlalchemy**: An ORM for working with databases.

**O365**: A library for integrating with Microsoft Office 365.

**werkzeug**: Provides security utilities like password hashing.


4. **Fill in the configuration file (config.py):**
     Keys are for O365 authentication. 
     Get your keys from: https://learn.microsoft.com/en-us/entra/fundamentals/entra-admin-center 
    ```sh
    client_id = 'your_client_id'
    client_secret = 'your_client_secret'
    SECRET_KEY = 'your_secret_key'


5. **Run the application:**
   ```sh
   python migrations.py
    python main.py

7. **Open in your web browser:**
   First run, "python migrations.py",
   Then after running "python main.py" in your command terminal...

    Click on the hyperlink: http://127.0.0.1:5000
