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


@apiBlueprint.route('/user/friends', methods=["GET"])
@auth.login_required
def getFriends():
    if not g.user: 
        print("ERROR: No user associated with the token to get friends for.")
        return "", constants.STATUS_SERVER_ERROR

    db.create_all()
    toReturn = { "count": 0, "friends": [] }
    if g.user.friends:
        for friendRow in g.user.friends:
            friend = User.query.get(friendRow.friendId)
            if friend: 
                userDetails = {"name": friend.name, "id": friend.id, "numCards": 0, "profileImgUrl": friend.profileImgUrl }
                if friend.cards:
                    userDetails["numCards"] = len(friend.cards)
                toReturn["friends"].append(userDetails)
                toReturn["count"] += 1
            else:
                print("WARNING: No Friend found with ID: " + str(friendRow.friendId))
    
    db.session.close()
    return jsonify(toReturn), constants.STATUS_OK


@apiBlueprint.route("/user/getVirgilJWT", methods=["GET"])
@auth.login_required
def getUserVirgilJWT():
    try:
        if not g.user:
            print('ERROR: No user to get Virgil JWT for.')
            return "", constants.STATUS_BAD_REQUEST

        crypto = VirgilCrypto()
        api_id = os.environ['VIRGIL_API_ID'] 
        api_key_id = os.environ['VIRGIL_API_KEY_ID']
        api_private_key = os.environ['VIRGIL_API_PRIVATE_KEY_ID']

        token_ttl = 20 # seconds
        imported_key = crypto.import_private_key(Utils.b64decode(api_private_key)).private_key

        # Instantiate token generator
        builder = JwtGenerator(
            api_id,
            imported_key,
            api_key_id,
            token_ttl,
            AccessTokenSigner()
        )

        token = builder.generate_token(str(g.user.id)).to_string()
        return jsonify({"token": token}), constants.STATUS_OK
    except Exception as err:
        print('Error getting the Virgil JWT: ' + str(err))
        return "", constants.STATUS_SERVER_ERROR

    return "", constants.STATUS_SERVER_ERROR


@apiBlueprint.route("/user/searchUser", methods=["GET"])
@auth.login_required
def searchUser():
    if "idCode" not in request.args:
        print("ERROR: Cannot search for users without invite code.")
        return "", constants.STATUS_BAD_REQUEST

    if g.user.idCode.upper() == request.args["idCode"].upper():
        print('ERROR: Cannot return the same user when searching idCode')
        return "", constants.STATUS_BAD_REQUEST

    idCode = request.args["idCode"]
    idCode = idCode.upper()
    db.create_all()
    targetUser = User.query.options(load_only("name", "id", "profileImgUrl")).filter_by(idCode=idCode).first()
    toReturn = {"count": 0 }
    if targetUser: 
        toReturn["count"] = 1
        toReturn["name"] = targetUser.name
        toReturn["id"] = targetUser.id
        toReturn["profileImgUrl"] = targetUser.profileImgUrl
    db.session.close()
    return jsonify(toReturn), constants.STATUS_OK    


@apiBlueprint.route('/user/idCode', methods=["GET"])
@auth.login_required
def getUserIdCode():
    if not g.user: 
        print("ERROR: No user associated with the token to get IdCode for.")
        return "", constants.STATUS_SERVER_ERROR

    numFriends = 0
    if g.user.friends:
        numFriends = len(g.user.friends)

    return jsonify({"idCode": g.user.idCode, "numFriends": numFriends}), constants.STATUS_OK    

# TODO: Search tags
# change circles env in EB (think about random domain vs particular domain)
# api key handling
@apiBlueprint.route('/user/search/cardholders', methods=["GET"])
@auth.login_required
def searchCardholders():
    if "cardId" not in request.args:
        print("ERROR: Cardholders cannot be obtained without cardId")
        return "", constants.STATUS_BAD_REQUEST

    db.create_all()
    cardId = request.args["cardId"]
    toReturn = {"numFirst": 0, "numSecond": 0, "first": [], "second": []}

    theCard = Card.query.get(cardId)

    if not theCard:
        print("ERROR: There is not card matching the given cardId: " + str(cardId))
        return "", constants.STATUS_BAD_REQUEST

    cardIds = []
    if theCard.objectType == constants.CARD_TYPE_TAG:
        cardsWithTag = Card.query.filter_by(tagId=theCard.id)
        for cardWithTag in cardsWithTag: 
            cardIds.append(int(cardWithTag.id))
    else:
        cardIds = [int(cardId)]

    # Search first degree friends with card
    for friendRow in g.user.friends:
        friend = User.query.get(friendRow.friendId)
        if not friend: 
            print("WARNING: No friend with id: " + str(friendRow.friendId))
            continue
        
        if not friend.cards:
            continue

        for oneCardId in cardIds:
            if oneCardId in friend.cards:
                toReturn["first"].append({"name": friend.name, "id": friend.id, "phoneNumber": friend.phoneNumber, \
                    "cardId": oneCardId, "cardName": getCardNameFromId(oneCardId)})
                toReturn["numFirst"] += 1 

        # Search second degree friends with card
        for secondDegreeFriendRow in friend.friends:
            # Ignore the current user in the list of friends
            if secondDegreeFriendRow.friendId == g.user.id:
                continue

            secondDegreeFriend = User.query.get(secondDegreeFriendRow.friendId)
            if not secondDegreeFriend: 
                print("WARNING: No second degree friend with id: " + str(secondDegreeFriendRow.friendId))
                continue
            
            if not secondDegreeFriend.cards:
                continue
            
            for oneCardId in cardIds:
                if oneCardId in secondDegreeFriend.cards:
                    toReturn["second"].append({"name": secondDegreeFriend.name, "id": secondDegreeFriend.id, \
                        "cardId": oneCardId, "cardName": getCardNameFromId(oneCardId), "friendName": friend.name})
                    toReturn["numSecond"] += 1 

    db.session.close()
    return jsonify(toReturn), constants.STATUS_OK


@apiBlueprint.route("/user/sendChatNotification", methods=["POST"])
@auth.login_required
def sendChatNotification():
    if "data" not in request.json:
        print("ERROR: Data object not found in notification request")
        return "", constants.STATUS_BAD_REQUEST

    if "to" not in request.json:
        print("ERROR: No recipient found in notification request")
        return "", constants.STATUS_BAD_REQUEST

    data = request.json["data"]
    recipientFcmToken = request.json["to"]
    data["partnerName"] = g.user.name # this user becomes the partner when the notification is read by recipient
    notificationObj = messaging.Notification(constants.CHAT_NOTIFICATION_TITLE.format(str(g.user.name)), \
                                            constants.CHAT_NOTIFICATION_BODY)
    utils.sendDeviceNotification(recipientFcmToken, notificationObj, data)
    return "", constants.STATUS_OK


@apiBlueprint.route("/user/profile", methods=["GET"])
@auth.login_required
def getProfile():
    db.create_all()

    # Check if profile is accessible to user
    accessible = False
    if "id" in request.args:
        if request.args["id"] == g.user.id:
            accessible = True
        else:
            if g.user.friends:
                for friendRow in g.user.friends:
                    if str(friendRow.friendId) == request.args["id"]:
                        accessible = True
                        break
    else:
        accessible = True

    if not accessible:
        print('ERROR: This user cannot access the profile.')
        db.session.close()
        return "", constants.STATUS_BAD_REQUEST

    thisUser = g.user if "id" not in request.args else User.query.get(request.args['id'])

    if not thisUser:
        print('ERROR: There is no user associated to get the profile for.')
        db.session.close()
        return "", constants.STATUS_BAD_REQUEST

    userCardIds = thisUser.cards
    responseString = {
        "name": thisUser.name,
        "phoneNumber": thisUser.phoneNumber,
        "cards": [],
        "upiID": thisUser.upiID,
        "profileImgUrl": thisUser.profileImgUrl,
    }

    if userCardIds:
        for cardId in userCardIds:
            cardName = getCardNameFromId(cardId)
            responseString["cards"].append({"name": cardName, "id": cardId})

    db.session.close()
    return jsonify(responseString), constants.STATUS_OK

@apiBlueprint.route("/user/updateUPI", methods=["POST"])
@auth.login_required
def updateUPI():
    if "upiID" not in request.json:
        print('ERROR: upiID parameter is required for updating UPI ID.')
        return "", constants.STATUS_BAD_REQUEST

    if not g.user:
        print('ERROR: There is no user associated with the token.')
        return "", constants.STATUS_BAD_REQUEST

    db.create_all()
    thisUser = g.user
    thisUser.upiID = request.json["upiID"]
    if (not commitToDB()):
        print('ERROR: Problem updating UPIID: ' + str(g.user.phoneNumber))
        return "", constants.STATUS_SERVER_ERROR

    return "", constants.STATUS_OK


@apiBlueprint.route("/user/updateCards", methods=["POST"])
@auth.login_required
def updateCards():
    if not g.user:
        print('ERROR: There is no user associated with the token.')
        return "", constants.STATUS_BAD_REQUEST
    db.create_all()
    thisUser = g.user
    
    # Cards
    selectedCards = json.loads(request.json["cards"])
    cards = []
    for selectedCard in selectedCards:
        if selectedCard["id"] not in cards:
            cards.append(selectedCard["id"])

    # remove the userid from existing cards
    if thisUser.cards is not None:
        for cardId in thisUser.cards:
            theCard = Card.query.get(cardId)
            if theCard is not None and theCard.users is not None:
                while thisUser.id in theCard.users: 
                    theCard.users.remove(thisUser.id) # there may be cases when duplicate ids exist so remove all.
                flag_modified(theCard, 'users')
    db.session.commit()
    print('Finished removing cards for user: ' + str(g.user.phoneNumber))

    thisUser.cards = cards

    # add the userid in the new cards
    for cardId in cards:
        theCard = Card.query.get(cardId)
        if theCard is not None:
            if theCard.users is None:
                theCard.users = []
            theCard.users.append(thisUser.id)
            flag_modified(theCard, 'users')
    print('Finished adding cards for user: ' + str(g.user.phoneNumber))

    flag_modified(thisUser, 'cards')
    if (not commitToDB()):
        print('ERROR: Could not update cards for ID: ' + str(thisUser.id))
        return "", constants.STATUS_SERVER_ERROR

    return "", constants.STATUS_OK

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