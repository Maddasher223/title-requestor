# webapp/__init__.py
from flask import Flask

app = Flask(
    __name__,
    template_folder='templates',
    static_url_path='/static',
    static_folder='static'
)

# Import routes after app creation to avoid circular imports
from . import routes