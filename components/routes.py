"""
components/routes.py (Legacy Compatibility Shim)
------------------------------------------------
Exports api_blueprint and register_blueprints pointing to the modular routes/ subpackage.
"""
from routes import register_blueprints
from routes.auth import auth_bp as api_blueprint

__all__ = ["register_blueprints", "api_blueprint"]
