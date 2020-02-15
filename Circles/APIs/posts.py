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
from Circles import constants, utils
from threading import Thread
from twilio.rest import Client
from virgil_crypto import VirgilCrypto
from virgil_crypto.access_token_signer import AccessTokenSigner
from virgil_sdk.jwt import JwtGenerator
from virgil_sdk.utils import Utils
from . import apiBlueprint, auth


@apiBlueprint.route("/posts/new", methods=["POST"])
@auth.login_required
def createNewPost():
    if "text" not in request.json: 
        print("ERROR: No text in the post to be created")
        return "", constants.STATUS_BAD_REQUEST

    text = request.json["text"]
    createdOn = datetime.datetime.now(tz=pytz.timezone(constants.TIMEZONE_KOLKATA))
    db.create_all()
    post = Post(text=text,createdOn=createdOn)
    g.user.posts.append(post)
    db.session.add(post)
    db.session.commit()

    friendFcmTokens = []
    if g.user.friends:
        for friendRow in g.user.friends:
            friend = User.query.get(friendRow.friendId)
            if friend:
                friendFcmTokens.append(friend.fcmToken)
    postId = post.id
    creatorName = g.user.name
    db.session.close()
    t = Thread(target=sendPostNotificationsToFriends, args=(friendFcmTokens, creatorName, postId))
    t.start()

    return "", constants.STATUS_OK


def createNotificationForNewPost(name):
    return messaging.Notification(constants.POST_NOTIFICATION_TITLE.format(name), \
                                  constants.POST_NOTIFICATION_BODY.format(name), os.environ["LOGO_URL"])


def sendPostNotificationsToFriends(fmcTokens, creatorName, postId):
    data = {
        "type": constants.POST_NOTIFICATION_TYPE,
        "id": str(postId)
    }
    notification = createNotificationForNewPost(creatorName)
    
    if fmcTokens: 
        for fcmToken in fmcTokens:
            utils.sendDeviceNotification(fcmToken, notification, data)
    
    return True


@apiBlueprint.route("/posts/all", methods=["GET"])
@auth.login_required
def getPosts():
    postType = "sent" if "type" not in request.args else request.args["type"]
    db.create_all()
    toReturn = { "count": 0, "posts": [] }
    if postType == "sent": 
        if g.user.posts:
            for post in g.user.posts:
                toReturn["posts"].append({"id": post.id, "text": post.text, "creatorId": post.creatorId, \
                   "creatorName": post.creator.name, "createdOn": utils.getDateTimeAsString(post.createdOn), "creatorImgUrl": post.creator.profileImgUrl})
                toReturn["count"] += 1
    else:
        allPosts = []
        if g.user.friends:
            for friendRow in g.user.friends: 
                friend = User.query.get(friendRow.friendId)
                if friend and friend.posts and len(friend.posts) > 0:
                    for post in friend.posts:
                        allPosts.append(post)

        if allPosts != []:
            allPosts = sorted(allPosts, key=lambda post: post.createdOn, reverse=True)
            for post in allPosts:
                toReturn["posts"].append({"id": post.id, "text": post.text, "creatorId": post.creatorId, \
                            "createdOn": utils.getDateTimeAsString(post.createdOn), "creatorImgUrl": post.creator.profileImgUrl, \
                            "creatorName": post.creator.name})
                toReturn["count"] += 1

    db.session.close()
    return jsonify(toReturn), constants.STATUS_OK


@apiBlueprint.route("/posts", methods=["GET"])
@auth.login_required
def getPostInfo():
    if "id" not in request.args:
        print("ERROR: No post id provided")
        return "", constants.STATUS_BAD_REQUEST

    db.create_all()
    postId = request.args["id"]
    post = Post.query.get(request.args["id"])
    if not post: 
        print('ERROR: No post found with given id: ' + str(postId))
        return "", constants.STATUS_BAD_REQUEST

    toReturn = {
        "id": post.id,
        "creatorName": post.creator.name,
        "creatorImgUrl": post.creator.profileImgUrl,
        "creatorId": post.creatorId,
        "text": post.text,
        "createdOn": utils.getDateTimeAsString(post.createdOn),
    }

    db.session.close()
    return jsonify(toReturn), constants.STATUS_OK

