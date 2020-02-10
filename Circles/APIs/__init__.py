from flask import Blueprint, Flask, jsonify, g, request, abort
from flask import current_app as app
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
from Circles.models import AuthCodeVerification, Card, db, FriendRequest, User, Friend, AccessRequest, Post
from firebase_admin import messaging
from sqlalchemy.orm import load_only
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import exc,literal
import datetime, json, pytz, random, requests, string, os
from Circles import constants

apiBlueprint = Blueprint('apiBlueprint', __name__)
auth = HTTPBasicAuth()

@auth.verify_password
def verify_password(username_or_token, password):
    # first try to authenticate by token
    user = User.verify_auth_token(username_or_token, os.environ['SECRET_KEY'])
    if not user:
        # try to authenticate with username/password
        user = User.query.filter_by(phoneNumber=username_or_token).first()
        if not user:
            print('ERROR: No user found for user name.')
            return False

    g.user = user
    return True


from . import accessRequests, authorization, cards, friendRequests, posts, users
