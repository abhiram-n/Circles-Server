from flask import Blueprint, Flask, jsonify, g, request, abort
from flask import current_app as app
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
from Circles.models import AuthCodeVerification, Card, db, FriendRequest, User, Friend, AccessRequest, Post
from firebase_admin import messaging
from sqlalchemy.orm import load_only
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import exc,literal, desc
import datetime, json, pytz, random, requests, string
from Circles import constants, utils
from threading import Thread
from twilio.rest import Client
from virgil_crypto import VirgilCrypto
from virgil_crypto.access_token_signer import AccessTokenSigner
from virgil_sdk.jwt import JwtGenerator
from virgil_sdk.utils import Utils
from . import apiBlueprint, auth


@apiBlueprint.route("/friendRequests/new", methods=["POST"])
@auth.login_required
def createNewFriendRequest():
    if "to" not in request.json:
        print("ERROR: There are no recipients for this request")
        return "", constants.STATUS_BAD_REQUEST

    if not g.user:
        print('ERROR: There is no user associated for friend request.')
        return "", constants.STATUS_BAD_REQUEST

    if request.json["to"] == g.user.id:
        print('ERROR: Cannot send friendrequest to the same user id: ' + str(request.json["to"]))
        return "", constants.STATUS_BAD_REQUEST

    to = request.json["to"]
    createdOn = datetime.datetime.now(tz=pytz.timezone(constants.TIMEZONE_KOLKATA))
    db.create_all()

    # Check if friend request already exists
    if FriendRequest.query.filter_by(fromUserId=g.user.id).filter_by(toUserId=to).first() or \
        FriendRequest.query.filter_by(fromUserId=to).filter_by(toUserId=g.user.id).first():
        print("ERROR: Friend request between: " + str(g.user.id) + " and: " + str(to) + " already exists")
        db.session.close()
        return "", constants.STATUS_CONFLICT_ERROR

    # Create new request
    friendRequest = FriendRequest(createdOn=createdOn, status=constants.FRIEND_REQUEST_ACTIVE)
    recipient = User.query.get(to)
    
    if not recipient:
        print("ERROR: No friend request recipient found with id: " + str(to))
        return "", constants.STATUS_BAD_REQUEST

    g.user.fRequests_sent.append(friendRequest)
    recipient.fRequests_rec.append(friendRequest)
    db.session.add(friendRequest)
    db.session.commit()
    
    notification = createNotificationForNewFriendRequest(g.user.name)
    data = {
        "requestId": str(friendRequest.id),
        "type": constants.FRIEND_REQUEST_NOTIFICATION_TYPE
    }
    fcmToken = recipient.fcmToken

    db.session.close()
    t = Thread(target=utils.sendDeviceNotification, args=(fcmToken, notification, data))
    t.start()
    return "", constants.STATUS_OK


def createNotificationForNewFriendRequest(sender):
    return messaging.Notification(constants.FRIEND_REQUEST_NOTIFICATION_TITLE, 
                                  constants.FRIEND_REQUEST_NOTIFICATION_BODY.format(sender))


@apiBlueprint.route('/friendRequests/cancel', methods=["POST"])
@auth.login_required
def cancelFriendRequest():
    if "requestId" not in request.json:
        print("ERROR: ID of the friend request to cancel is missing")
        return "", constants.STATUS_BAD_REQUEST

    if not g.user:
        print('ERROR: There is no user associated for friend request cancellation.')
        return "", constants.STATUS_BAD_REQUEST

    requestId = request.json["requestId"]
    db.create_all()
    friendRequest = FriendRequest.query.get(requestId)
    if not friendRequest:
        print("ERROR: No friend request found with id: " + str(requestId))
        return "", constants.STATUS_BAD_REQUEST
    g.user.fRequests_rec.remove(friendRequest)
    friendRequest.sender.fRequests_sent.remove(friendRequest)
    db.session.delete(friendRequest)
    if (not commitToDB()):
        print('ERROR: Problem cancelling the friend request')
        return "", constants.STATUS_SERVER_ERROR
    
    return "", constants.STATUS_OK


@apiBlueprint.route('/friendRequests/sent', methods=["GET"])
@auth.login_required
def getFriendRequestsSent():
    if not g.user:
        print('ERROR: There is no user associated for getting friend requests sent.')
        return "", constants.STATUS_BAD_REQUEST

    db.create_all()
    friendRequests = g.user.fRequests_sent
    if not friendRequests:
        return jsonify({"count": 0}), constants.STATUS_OK
    
    count = len(friendRequests)
    toReturn = {"count": count, "requests": []}
    for friendRequest in friendRequests:
        recipientName = friendRequest.recipient.name
        toReturn['requests'].append({"requestId": friendRequest.id,  \
            "id": friendRequest.toUserId, "name": recipientName, "createdOn": utils.getDateTimeAsString(friendRequest.createdOn), \
            "profileImgUrl": friendRequest.recipient.profileImgUrl, "resolvedOn": utils.getDateTimeAsString(friendRequest.resolvedOn), "status": friendRequest.status})
    db.session.close()
    return jsonify(toReturn), constants.STATUS_OK


@apiBlueprint.route('/friendRequests/received', methods=["GET"])
@auth.login_required
def getFriendRequestsReceived():
    if not g.user:
        print('ERROR: There is no user associated for getting friend request received.')
        return "", constants.STATUS_BAD_REQUEST

    status = request.args["status"] if "status" in request.args else None
    db.create_all()
    friendRequests = None
    if status:
        friendRequests = FriendRequest.query.filter_by(toUserId=g.user.id).filter_by(status=status).order_by(desc(FriendRequest.createdOn)).all()
    else: 
        friendRequests = FriendRequest.query.filter_by(toUserId=g.user.id).order_by(desc(FriendRequest.createdOn)).all()
    if not friendRequests:
        return jsonify({"count": 0}), constants.STATUS_OK
    
    count = len(friendRequests)
    toReturn = {"count": count, "requests": []}
    for friendRequest in friendRequests:
        senderName = friendRequest.sender.name
        toReturn['requests'].append({"requestId": friendRequest.id, "name": senderName, "phoneNumber": friendRequest.sender.phoneNumber, \
            "id": friendRequest.fromUserId, "createdOn": utils.getDateTimeAsString(friendRequest.createdOn), "profileImgUrl": friendRequest.sender.profileImgUrl, \
            "resolvedOn": utils.getDateTimeAsString(friendRequest.resolvedOn), "status": friendRequest.status})
    db.session.close()
    return jsonify(toReturn), constants.STATUS_OK


@apiBlueprint.route("/friendRequests/respond", methods=["POST"])
@auth.login_required
def respondToFriendRequest():
    if "action" not in request.json:
        print("ERROR: There are no actions specified in the friend request response")
        return "", constants.STATUS_BAD_REQUEST

    if "requestId" not in request.json:
        print("ERROR: ID of the friend request is missing")
        return "", constants.STATUS_BAD_REQUEST

    if not g.user:
        print('ERROR: There is no user associated for friend request response.')
        return "", constants.STATUS_BAD_REQUEST

    action = request.json["action"]
    requestId = request.json["requestId"]
    db.create_all()

    if "limit" in request.json:
        limit = request.json["limit"]
        if g.user.friends and len(g.user.friends) >= limit:
            print('ERROR: User: ' + str(g.user.id) + ' has reached the limit of friend requests')
            return "", constants.STATUS_PRECONDITION_FAILED

    friendRequest = FriendRequest.query.get(requestId)
    if not friendRequest:
        print("ERROR: No friend request found with id: " + str(requestId))
        return "", constants.STATUS_BAD_REQUEST

    if g.user.id != friendRequest.toUserId:
        print("ERROR: Cannot respond to request that is not sent to the user id: " + str(g.user.id))
        db.session.close()
        return "", constants.STATUS_BAD_REQUEST

    if friendRequest.status == action:
        print("WARNING: Friend request status already at the desired state:" + str(action))
        db.session.close()
    else:
        data = {
            "requestId": str(friendRequest.id),
            "type": constants.FRIEND_REQUEST_NOTIFICATION_TYPE,
            "isUserSender": "true" # the notification is sent to the user who sent the request
        }
        fcmToken = friendRequest.sender.fcmToken

        notification = createNotificationForDeclinedFriendRequest(g.user.name)
        friendRequest.status = action
        timeNow = datetime.datetime.now(tz=pytz.timezone(constants.TIMEZONE_KOLKATA))
        friendRequest.resolvedOn = timeNow
        if (action == constants.FRIEND_REQUEST_ACCEPTED):
            friendFirstRow = Friend(fRequestId=requestId, friendId=friendRequest.fromUserId, startedOn=timeNow)
            g.user.friends.append(friendFirstRow)
            friend = User.query.get(friendRequest.fromUserId)
            friendSecondRow = Friend(fRequestId=requestId, friendId=g.user.id, startedOn=timeNow)
            friend.friends.append(friendSecondRow)
            db.session.add(friendFirstRow)
            db.session.add(friendSecondRow)
            notification = createNotificationForAcceptedFriendRequest(g.user.name)
            
        if (not commitToDB()):
            print('ERROR: Problem resolving the friend request')
            return "", constants.STATUS_SERVER_ERROR

    t = Thread(target=utils.sendDeviceNotification, args=(fcmToken, notification, data))
    t.start()

    return "", constants.STATUS_OK


def createNotificationForAcceptedFriendRequest(recipient):
    return messaging.Notification(constants.FRIEND_REQUEST_ACCEPTED_TITLE.format(recipient), \
                                constants.FRIEND_REQUEST_ACCEPTED_BODY)


def createNotificationForDeclinedFriendRequest(recipient):
    return messaging.Notification(constants.FRIEND_REQUEST_DECLINED_TITLE.format(recipient), \
                                constants.FRIEND_REQUEST_DECLINED_BODY)


@apiBlueprint.route("/friends/remove", methods=["POST"])
@auth.login_required
def removeFriend():
    if "friendId" not in request.json:
        print('ERROR: No friendID field provided to remove.')
        return "", constants.STATUS_BAD_REQUEST

    if not g.user.friends or len(g.user.friends): 
        print("ERROR: Cannot remove friend as user has no friends in db.")
        return "", constants.STATUS_BAD_REQUEST

    friendId = request.json["friendId"]
    db.create_all()

    for friendRow in g.user.friends:
        if friendId == friendRow.friendId:
            g.user.friends.remove(friendRow)
            fRequest = FriendRequest.query.get(friendRow.fRequestId)
            db.session.delete(friendRow)
            db.session.delete(fRequest) #TODO: Try to see if it is removed from user's requests
            if (not commitToDB()):
                print("ERROR: Something went wrong in deleting the friend ID:" + str(friendId))
                return "", constants.STATUS_SERVER_ERROR
            
            return "", constants.STATUS_OK
        
    db.session.close()
    print("ERROR: User has no friend with friendID: " + str(friendId))
    return "", constants.STATUS_SERVER_ERROR


@apiBlueprint.route("/friendRequests", methods=["GET"])
@auth.login_required
def getFriendRequestInfo():
    if "id" not in request.args:
        print("ERROR: No id of friend request provided")
        return "", constants.STATUS_BAD_REQUEST

    requestId = request.args["id"]
    db.create_all()
    friendRequest = FriendRequest.query.get(requestId)
    if not friendRequest:
        print("ERROR: No friend request found for getFriendRequest with id: " + str(requestId))
        db.session.close()
        return "", constants.STATUS_BAD_REQUEST

    if friendRequest.toUserId != g.user.id and friendRequest.fromUserId != g.user.id:
        print("ERROR: Cannot get Friend request info when the user is not involved. User: " + str(g.user.id) + " Req: " + str(requestId))
        db.session.close()
        return "", constants.STATUS_BAD_REQUEST

    toReturn = {
        "senderId": friendRequest.fromUserId,
        "senderName": friendRequest.sender.name,
        "senderImgUrl": friendRequest.sender.profileImgUrl,
        "senderPhone": friendRequest.sender.phoneNumber,
        "numSenderCards": 0 if friendRequest.sender.cards is None else len(friendRequest.sender.cards),
        "recipientId": friendRequest.toUserId,
        "recipientName": friendRequest.recipient.name,
        "recipientImgUrl": friendRequest.recipient.profileImgUrl,
        "recipientPhone": friendRequest.recipient.phoneNumber,
        "numRecipientCards": 0 if friendRequest.recipient.cards is None else len(friendRequest.recipient.cards),
        "createdOn": utils.getDateTimeAsString(friendRequest.createdOn),
        "resolvedOn": utils.getDateTimeAsString(friendRequest.resolvedOn),
        "status": friendRequest.status,
    } 

    db.session.close()
    return jsonify(toReturn), constants.STATUS_OK

# make sure to call db.create_all() before this.
def commitToDB():
    committed = False
    try:
        db.session.commit()
        committed = True
    except Exception as err:
        db.session.rollback()
        print('ERROR: Exception while committing to database: ' + str(err))
    finally:
        db.session.close()

    return committed