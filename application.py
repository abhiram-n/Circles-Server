from flask import Blueprint, Flask, jsonify, g, request, abort
import os, json, random, datetime, firebase_admin, urllib.parse
from Circles import create_app, create_db
from Circles.models import db
from Circles.APIs import apiBlueprint, auth


# Firebase configuration
firebase_app = firebase_admin.initialize_app()

# Main application configuration
application = create_app()
db.init_app(application)
application.register_blueprint(apiBlueprint)

if __name__ == "__main__":
    application.run()