from itsdangerous import (TimedJSONWebSignatureSerializer as Serializer, SignatureExpired, BadSignature)
from sqlalchemy.dialects.postgresql import ARRAY
from flask import abort
from flask_sqlalchemy import SQLAlchemy
from Circles import constants

db = SQLAlchemy()

class Card(db.Model):
    __tablename__ = "card"
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(), unique=False)
    tagId = db.Column(db.Integer(), unique=False)
    objectType = db.Column(db.String(), unique=False)
    rewards = db.Column(db.Numeric(), unique=False)
    minAmount = db.Column(db.Numeric(), unique=False)
    users = db.Column(ARRAY(db.String()), unique=False)

class User(db.Model):
    __tablename__ = "user"
    id = db.Column(db.Integer(), primary_key=True)
    idCode = db.Column(db.String(), unique=True)
    inviteCodeUsed = db.Column(db.String(), unique=False)
    name = db.Column(db.String(40), unique=False)
    phoneNumber = db.Column(db.String(15), unique=True)
    password = db.Column(db.Unicode(200), unique=False)
    fcmToken = db.Column(db.String(), unique=False)
    upiID = db.Column(db.String(100), unique=False)
    cards = db.Column(ARRAY(db.Integer()), unique=False)
    suspended = db.Column(db.Boolean(), unique=False)
    joined = db.Column(db.String(), unique=False)
    friends = db.relationship("Friend", backref="user", lazy=True, foreign_keys = 'Friend.userId')
    profileImgUrl = db.Column(db.String(), unique=False)
    posts = db.relationship("Post", backref="creator", order_by="desc(Post.createdOn)", lazy=True, foreign_keys='Post.creatorId')
    fRequests_rec = db.relationship("FriendRequest", backref="recipient", order_by="desc(FriendRequest.createdOn)", lazy=True, cascade="all, delete, delete-orphan", foreign_keys = 'FriendRequest.toUserId')
    fRequests_sent = db.relationship("FriendRequest", backref="sender", order_by="desc(FriendRequest.createdOn)", lazy=True, cascade="all, delete, delete-orphan", foreign_keys = 'FriendRequest.fromUserId')
    aRequests_rec = db.relationship("AccessRequest", backref="recipient", order_by="desc(AccessRequest.createdOn)", lazy=True, cascade="all, delete, delete-orphan", foreign_keys = 'AccessRequest.toUserId')
    aRequests_sent = db.relationship("AccessRequest", backref="sender", order_by="desc(AccessRequest.createdOn)", lazy=True, cascade="all, delete, delete-orphan", foreign_keys = 'AccessRequest.fromUserId')

    def generate_auth_token(self, expiration, key):
        s = Serializer(key, expiration)
        return s.dumps({'id': self.id})

    @property
    def is_active(self):
        return not self.suspended

    @staticmethod
    def verify_auth_token(token, key):
        s = Serializer(key)
        try:
            data = s.loads(token)
        except SignatureExpired:
            print("ERROR: The token has expired.")
            abort(constants.STATUS_GONE)
            return None  # valid token, but expired
        except BadSignature:
            print("ERROR: The token is invalid")
            return None  # invalid token
        user = User.query.get(data['id'])
        return user


class AuthCodeVerification(db.Model):
    __tablename__ = "AuthCodeVerification"
    phoneNumber = db.Column(db.String(), primary_key=True)
    code = db.Column(db.String(), unique=False)
    expiration = db.Column(db.DateTime(timezone=True), unique=False)


class FriendRequest(db.Model):
    __tablename__ = "FriendRequest"
    id = db.Column(db.Integer(), primary_key=True)
    fromUserId = db.Column(db.Integer(), db.ForeignKey('user.id'))
    toUserId = db.Column(db.Integer(), db.ForeignKey('user.id'))
    createdOn = db.Column(db.DateTime(timezone=True))
    resolvedOn = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.Integer())


class Friend(db.Model):
    __tablename__ = "Friend"
    id = db.Column(db.Integer(), primary_key=True)
    userId = db.Column(db.Integer(), db.ForeignKey('user.id'))
    friendId = db.Column(db.Integer(), db.ForeignKey('user.id'))
    fRequestId = db.Column(db.Integer(), db.ForeignKey('FriendRequest.id'))
    startedOn = db.Column(db.DateTime(timezone=True))


class AccessRequest(db.Model):
    __tablename__ = "AccessRequest"
    id = db.Column(db.Integer(), primary_key=True)
    fromUserId = db.Column(db.Integer(), db.ForeignKey('user.id'))
    toUserId = db.Column(db.Integer(), db.ForeignKey('user.id'))
    cardId = db.Column(db.Integer(), unique=False)
    amount = db.Column(db.Integer(), unique=False)
    shortDesc = db.Column(db.String(), unique=False)
    status = db.Column(db.Integer(), unique=False)
    createdOn = db.Column(db.DateTime(timezone=True))
    resolvedOn = db.Column(db.DateTime(timezone=True))


class Post(db.Model):
    __tablename__ = "Post"
    id = db.Column(db.Integer(), primary_key =True)
    text = db.Column(db.String())
    creatorId = db.Column(db.Integer(), db.ForeignKey('user.id')) 
    createdOn = db.Column(db.DateTime(timezone=True)) 