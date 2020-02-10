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


@apiBlueprint.route("/accessRequests/new", methods=["POST"])
@auth.login_required
def createNewAccessRequest():
    if "to" not in request.json:
        print("ERROR: No user id provided to send the access request to")
        return "", constants.STATUS_BAD_REQUEST

    if "amount" not in request.json:
        print("ERROR: No amount provided to send access request for")
        return "", constants.STATUS_BAD_REQUEST

    if "cardId" not in request.json:
        print("ERROR: No cardId provided to send access request for")
        return "", constants.STATUS_BAD_REQUEST

    amount = request.json["amount"]
    to = request.json["to"]
    cardId = int(request.json["cardId"])

    db.create_all()
    recipient = User.query.options(load_only('fcmToken')).get(to)
    if not recipient:
        print("ERROR: No user found with id: " + str(to) + " to send access request to")
        db.session.close()
        return "", constants.STATUS_BAD_REQUEST

    timeNow = datetime.datetime.now(tz=pytz.timezone(constants.TIMEZONE_KOLKATA))
    accessRequest = AccessRequest(cardId=cardId, amount=amount, status=constants.ACCESS_REQUEST_UNACCEPTED, createdOn=timeNow)
    g.user.aRequests_sent.append(accessRequest)
    recipient.aRequests_rec.append(accessRequest)
    db.session.add(accessRequest)
    db.session.commit()

    # Send notification in parallel
    notification = createNotificationForAccessRequest(g.user.name, cardId)
    fcmToken = recipient.fcmToken
    data = {
        "requestId": str(accessRequest.id),
        "type": constants.ACCESS_REQUEST_NOTIFICATION_TYPE,
    }

    db.session.close()
    t = Thread(target=utils.sendDeviceNotification, args=(fcmToken, notification, data))
    t.start()
    return "", constants.STATUS_OK


def createNotificationForAccessRequest(name, cardId):
    cardName = getCardNameFromId(cardId)
    return messaging.Notification(constants.ACCESS_REQUEST_NOTIFICATION_TITLE.format(name),
                                  constants.ACCESS_REQUEST_NOTIFICATION_BODY.format(name, cardName))


@apiBlueprint.route("/accessRequests", methods=["GET"])
@auth.login_required
def getAccessRequestInfo():
    if "id" not in request.args:
        print("ERROR: No id of access request provided")
        return "", constants.STATUS_BAD_REQUEST

    requestId = request.args["id"]
    db.create_all()
    accessRequest = AccessRequest.query.get(requestId)
    if not accessRequest:
        print("ERROR: No access request found for getAccessRequest with id: " + str(requestId))
        db.session.close()
        return "", constants.STATUS_BAD_REQUEST

    if accessRequest.toUserId != g.user.id and accessRequest.fromUserId != g.user.id:
        print("ERROR: Cannot get access request info when the user is not involved. User: " + str(g.user.id) + " Req: " + str(requestId))
        db.session.close()
        return "", constants.STATUS_BAD_REQUEST

    toReturn = {
        "senderId": accessRequest.fromUserId,
        "senderName": accessRequest.sender.name,
        "senderPhoneNumber": accessRequest.sender.phoneNumber,
        "senderFcmToken": accessRequest.sender.fcmToken,
        "senderImgUrl": accessRequest.sender.profileImgUrl,
        "recipientId": accessRequest.toUserId,
        "recipientName": accessRequest.recipient.name,
        "recipientPhoneNumber": accessRequest.recipient.phoneNumber,
        "recipientFcmToken": accessRequest.recipient.fcmToken,
        "recipientImgUrl": accessRequest.recipient.profileImgUrl,
        "amount": accessRequest.amount,
        "cardId": accessRequest.cardId,
        "cardName": getCardNameFromId(accessRequest.cardId),
        "status": accessRequest.status,
        "createdOn": utils.getDateTimeAsString(accessRequest.createdOn)
    } 

    db.session.close()
    return jsonify(toReturn), constants.STATUS_OK


@apiBlueprint.route("/accessRequests/respond", methods=["POST"])
@auth.login_required
def respondToAccessRequest():
    if "requestId" not in request.json:
        print("ERROR: No access request id provided to respond to")
        return "", constants.STATUS_BAD_REQUEST

    if "action" not in request.json:
        print("ERROR: No status provided to respond to access request with")
        return "", constants.STATUS_BAD_REQUEST

    action = request.json["action"]
    requestId = request.json["requestId"]
    db.create_all()
    accessRequest = AccessRequest.query.get(requestId)
    if g.user.id != accessRequest.toUserId:
        print("ERROR: Only the sender can respond to an access request: " + str(g.user.id))
        return "", constants.STATUS_BAD_REQUEST

    if accessRequest.status == action:
        print("WARNING: Access request status already at the desired state:" + str(action))
        db.session.close()
    else:
        data = {
            "requestId": str(accessRequest.id),
            "type": constants.ACCESS_REQUEST_NOTIFICATION_TYPE,
            "isUserSender": "true" # the notification is sent to the user who created/sent the request
        }

        fcmToken = accessRequest.sender.fcmToken
        accessRequest.status = action
        accessRequest.resolvedOn = datetime.datetime.now(tz=pytz.timezone(constants.TIMEZONE_KOLKATA))
        if (action == constants.ACCESS_REQUEST_ACCEPTED):
            notification = createNotificationForAcceptedAccessRequest(g.user.name)
        else:
            notification = createNotificationForDeclinedAccessRequest(g.user.name)
            
        if (not commitToDB()):
            print('ERROR: Problem resolving the access request')
            return "", constants.STATUS_SERVER_ERROR

        t = Thread(target=utils.sendDeviceNotification, args=(fcmToken, notification, data))
        t.start()

    return "", constants.STATUS_OK


def createNotificationForAcceptedAccessRequest(recipient):
    return messaging.Notification(constants.ACCESS_REQUEST_ACCEPTED_TITLE.format(recipient), \
                                constants.ACCESS_REQUEST_ACCEPTED_BODY)


def createNotificationForDeclinedAccessRequest(recipient):
    return messaging.Notification(constants.ACCESS_REQUEST_DECLINED_TITLE.format(recipient), \
                                constants.ACCESS_REQUEST_DECLINED_BODY)


@apiBlueprint.route("/accessRequests/received", methods=["GET"])
@auth.login_required
def getAccessRequestsReceived():
    if not g.user:
        print('ERROR: There is no user associated for getting access requests received.')
        return "", constants.STATUS_BAD_REQUEST

    db.create_all()
    accessRequests = AccessRequest.query.filter_by(toUserId=g.user.id).order_by(desc(AccessRequest.createdOn)).all()
    if not accessRequests:
        return jsonify({"count": 0}), constants.STATUS_OK
    
    count = len(accessRequests)
    toReturn = {"count": count, "requests": []}
    for accessRequest in accessRequests:
        senderName = accessRequest.sender.name
        cardName = getCardNameFromId(accessRequest.cardId)
        toReturn['requests'].append({"requestId": accessRequest.id, "cardId": accessRequest.cardId, "cardName": cardName, \
            "id": accessRequest.fromUserId, "name": senderName, "createdOn": utils.getDateTimeAsString(accessRequest.createdOn), \
            "resolvedOn": utils.getDateTimeAsString(accessRequest.resolvedOn), "status": accessRequest.status, \
            "profileImgUrl": accessRequest.sender.profileImgUrl, "amount": accessRequest.amount})
    db.session.close()
    return jsonify(toReturn), constants.STATUS_OK


@apiBlueprint.route("/accessRequests/sent", methods=["GET"])
@auth.login_required
def getAccessRequestsSent():
    if not g.user:
        print('ERROR: There is no user associated for getting access requests sent.')
        return "", constants.STATUS_BAD_REQUEST

    db.create_all()
    accessRequests = AccessRequest.query.filter_by(fromUserId=g.user.id).order_by(desc(AccessRequest.createdOn)).all()
    if not accessRequests:
        return jsonify({"count": 0}), constants.STATUS_OK
    
    count = len(accessRequests)
    toReturn = {"count": count, "requests": []}
    for accessRequest in accessRequests:
        recipientName = accessRequest.recipient.name
        cardName = getCardNameFromId(accessRequest.cardId)
        toReturn['requests'].append({"requestId": accessRequest.id, "cardId": accessRequest.cardId, "cardName": cardName, \
            "id": accessRequest.toUserId, "name": recipientName, "profileImgUrl": accessRequest.recipient.profileImgUrl, \
            "createdOn": utils.getDateTimeAsString(accessRequest.createdOn), "resolvedOn": utils.getDateTimeAsString(accessRequest.resolvedOn), \
            "status": accessRequest.status, "amount": accessRequest.amount})
    db.session.close()
    return jsonify(toReturn), constants.STATUS_OK


def getCardNameFromId(cardId):
    card = Card.query.options(load_only('name')).get(cardId)
    if not card:
        print('ERROR: No card with cardId: ' + cardId)
        return None
    return card.name

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