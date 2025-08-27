# webapp/__init__.py
from flask import Flask

# Initialize the app and tell it where to find templates and static files
app = Flask(__name__, template_folder='templates', static_folder='static')

# Import the routes after the app is created to avoid circular imports
from . import routes