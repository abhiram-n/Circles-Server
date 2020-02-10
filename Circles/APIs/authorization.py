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


@apiBlueprint.route("/auth/signup", methods=["POST"])
def signup():
    if ("name" not in request.json or
       "phoneNumber" not in request.json or "cards" not in request.json or
       "fcmToken" not in request.json):
        print('ERROR: One of the required fields is missing')
        return "", constants.STATUS_BAD_REQUEST

    if ("password" not in request.json and "phoneAuth" not in request.json):
        print('ERROR: No password or phone verification found.')
        return "", constants.STATUS_BAD_REQUEST

    name = request.json["name"]
    phoneNumber = request.json["phoneNumber"]
    inviteCodeUsed = request.json["inviteCode"]
    fcmToken = ""
    profileImgUrl = "" if "profileImgUrl" not in request.json else request.json["profileImgUrl"]
    fcmToken = "" if "fcmToken" not in request.json else request.json["fcmToken"]
    created_time = utils.getDateTimeAsString(datetime.datetime.now(tz=pytz.timezone(constants.TIMEZONE_KOLKATA)))

    # Cards
    selectedCards = json.loads(request.json["cards"])
    cards = []
    for selectedCard in selectedCards:
        cards.append(selectedCard["id"])

    strPhone = str(phoneNumber)
    print('Adding user: ' + strPhone[-4:])
    db.create_all()

    # Check if IDCode is unique
    idCode = utils.generateIdCode()
    while User.query.filter_by(idCode=idCode).first():
        idCode = utils.generateIdCode()

    # Check if phone number is unique
    oldUser = User.query.filter_by(phoneNumber=phoneNumber).first()
    if oldUser:
        print('ERROR: User with phone number already exists')
        db.session.close()
        return "", constants.STATUS_CONFLICT_ERROR
    
    newUser = User(name=name, fcmToken=fcmToken, upiID="", phoneNumber=phoneNumber, inviteCodeUsed=inviteCodeUsed,
                   cards=cards, suspended=False, joined=created_time, idCode=idCode, profileImgUrl=profileImgUrl)

    # SQLAlchemy not aware of ARRAY changes unless flag_modified is called
    flag_modified(newUser, 'cards')
    db.session.add(newUser)

    try:
        db.session.flush()
        for selectedCard in selectedCards:
            theCard = Card.query.get(selectedCard["id"])
            if theCard is not None:
                if theCard.users is None: 
                    theCard.users = []
                theCard.users.append(newUser.id)
                flag_modified(theCard, 'users')
        db.session.commit()
        newUserId = newUser.id
        newUserPhone = newUser.phoneNumber
        access_token = newUser.generate_auth_token(expiration=constants.TOKEN_EXPIRATION, key=os.environ['SECRET_KEY']).decode('ascii')
    except exc.IntegrityError as ex:
        db.session.rollback()
        print('ERROR: For User: ' + str(newUser.phoneNumber) + '. Exception while committing to database: ' + str(ex))
        return "", constants.STATUS_CONFLICT_ERROR        
    except Exception as err:
        db.session.rollback()
        print('ERROR: For User: ' + str(newUser.phoneNumber) + '. Exception while committing to database: ' + str(err))
        return "", constants.STATUS_SERVER_ERROR
    finally:
        db.session.close()

    return jsonify({'access_token': access_token, 'id': newUserId, "phoneNumber": newUserPhone}), constants.STATUS_OK


@apiBlueprint.route("/auth/phoneAuthLogin", methods=["POST"])
def loginAfterPhoneAuth():
    if ("phoneNumber" not in request.json or "fcmToken" not in request.json):
        print("ERROR: Required parameters missing in phoneAuthLogin")
        return "", constants.STATUS_BAD_REQUEST
    phoneNumber = request.json['phoneNumber']
    fcmToken = ""
    if request.json['fcmToken']:
        fcmToken = request.json['fcmToken']

    db.create_all()
    currentUser = User.query.filter_by(phoneNumber=phoneNumber).first()

    if not currentUser: 
        print("ERROR: Failed to fetch user with phone: " + str(phoneNumber))
        return "", constants.STATUS_UNAUTHORIZED

    currentUser.fcmToken = fcmToken
    currentUser.suspended = False
    access_token = currentUser.generate_auth_token(expiration=constants.TOKEN_EXPIRATION, key=os.environ['SECRET_KEY']).decode('ascii')
    try:
        db.session.commit()
    except Exception as err:
        db.session.rollback()
        print('ERROR: Exception while committing to database for phone: ' + str(phoneNumber) + ' error:' + str(err))
        db.session.close()
        return "", constants.STATUS_SERVER_ERROR
    
    userId = currentUser.id
    userPhoneNumber = currentUser.phoneNumber
    db.session.close()
    return jsonify({'access_token': access_token, "id": userId, "phoneNumber": userPhoneNumber}), constants.STATUS_OK


@apiBlueprint.route("/auth/userExists", methods=["GET"])
def checkIfUserExists():
    if "idCode" not in request.args:
        print('ERROR: No idCode provided to check invite code for')
        return "", constants.STATUS_BAD_REQUEST
    
    idCode = request.args["idCode"]
    idCode = idCode.upper()
    db.create_all()
    exists = 0
    invitee = User.query.filter_by(idCode=idCode).first()
    if invitee:
        exists = 1

    db.session.close()
    return jsonify({"exists": exists}), constants.STATUS_OK


@apiBlueprint.route("/auth/sendAuthCode", methods=["POST"])
def sendAuthCode():
    if "phoneNumber" not in request.json:
        print('ERROR: No phone number found to send code to.')
        return "", constants.STATUS_BAD_REQUEST

    mustExist = None if "mustExist" not in request.json else request.json["mustExist"]
    codeLength = constants.AUTH_CODE_LENGTH if "length" not in request.json else request.json["length"]
    db.create_all()
    phoneNumber = request.json["phoneNumber"]
    hashkey = os.environ["APP_KEY"]

    if mustExist is not None:
        currentUser = User.query.filter_by(phoneNumber=phoneNumber).first()
        if mustExist and not currentUser:
            print('ERROR: Not sending as there is no user to verify with: ' + str(phoneNumber))
            db.session.close()
            return "", constants.STATUS_PRECONDITION_FAILED
        elif currentUser and not mustExist:
            print('ERROR: Not sending code as user already exists: ' + str(phoneNumber))
            db.session.close()
            return "", constants.STATUS_PRECONDITION_FAILED

    code = utils.generateAuthCode(codeLength)
    expiration = datetime.datetime.now(tz=pytz.timezone(constants.TIMEZONE_KOLKATA)) + datetime.timedelta(minutes=10)

    # Is there any existing verification left
    oldVerification = AuthCodeVerification.query.filter_by(phoneNumber=phoneNumber).first()
    if oldVerification: 
        print('Found an old verification')
        oldVerification.code = code
        oldVerification.expiration = expiration
    else:
        verification = AuthCodeVerification(phoneNumber=phoneNumber, code=code, expiration=expiration)
        db.session.add(verification)

    if (not commitToDB()):
        print('ERROR: Problem creating verification for number: ' + str(phoneNumber))
        return "", constants.STATUS_SERVER_ERROR

    smsBody = code + " is your code to log in to Circles. This code will expire in 10 minutes. \n\n" + hashkey
    if not utils.sendSMS(smsBody, phoneNumber):
        print('ERROR: Could not send SMS to phone: ' + str(phoneNumber))
        return "", constants.STATUS_BAD_REQUEST

    return "", constants.STATUS_OK


@apiBlueprint.route("/auth/verifyAuthCode", methods=["POST"])
def verifyAuthCode():
    if "phoneNumber" not in request.json:
        print('ERROR: No phone number found to verify code for.')
        return "", constants.STATUS_BAD_REQUEST

    if "code" not in request.json:
        print('ERROR: No code received for verification')
        return "", constants.STATUS_BAD_REQUEST

    phoneNumber = request.json["phoneNumber"]
    code = request.json["code"]
    db.create_all()

    # ensure verification is pending
    pendingVerification = AuthCodeVerification.query.filter_by(phoneNumber=phoneNumber).first()
    if not pendingVerification:
        print('ERROR: No verification pending for this phone number: ' + str(phoneNumber))
        db.session.close()
        return "", constants.STATUS_BAD_REQUEST

    # Check if code is the same
    if code != pendingVerification.code:
        db.session.close()
        return jsonify({"status": constants.CODE_VERIFICATION_FAILED}), constants.STATUS_OK       
        
    # Check expiry and delete the verification record
    now = datetime.datetime.now(tz=pytz.timezone(constants.TIMEZONE_KOLKATA))
    status = constants.CODE_VERIFICATION_SUCCEEDED
    if now > pendingVerification.expiration:
        print('ERROR: Code has expired for phone: ' + str(phoneNumber))
        status = constants.CODE_VERIFICATION_EXPIRED
    db.session.delete(pendingVerification)
    commitToDB() # ignore failures here, not important to fail the request
    return jsonify({"status": status}), constants.STATUS_OK


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
