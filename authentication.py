from flask import request
from O365 import Account
from config import*

credentials = (client_id, client_secret)
scopes = ['Mail.ReadWrite', 'Mail.Send']
account = Account(credentials)  # Don't pass scopes here
if not account.is_authenticated:
    account.authenticate(scopes=scopes)  # 

if account.is_authenticated:
    print("✅ Successfully authentication!")
else:
    print("❌ Authentication failed. Please try again.")


# The later is exactly the same as passing scopes to the authenticate method like so:
# account = Account(credentials)
# account.authenticate(scopes=scopes)