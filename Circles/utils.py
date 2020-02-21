import datetime, pytz, random, string, os
from twilio.rest import Client
from Circles import constants
from firebase_admin import messaging

def sendDeviceNotification(registration_token, notification, data):
    try:
        message = messaging.Message(data=data, notification=notification,
                                    android=messaging.AndroidConfig( priority='normal', notification=messaging.AndroidNotification( sound='default', channel_id=constants.FIREBASE_CHANNEL)),
                                    token=registration_token)
        response = messaging.send(message)
    except Exception as err:
        print('Error while sending notification: ' + str(err))
        return False
    return True

def sendSMS(smsBody, phoneNumber):
    try:
        account_sid = os.environ['TWILIO_ACCOUNT_SID']
        auth_token = os.environ['TWILIO_AUTH_TOKEN']
        client = Client(account_sid, auth_token)
        message = client.messages.create(body=smsBody, from_=os.environ['TWILIO_PHONE_NUMBER'], to=phoneNumber)
    except Exception as err:
        print('Failed to send sms: ' + str(err))
        return False

    return True

def sendSMSToFounders(smsBody):
    try:
        phoneNumbers = [os.environ['ABHIRAM'], os.environ['ANCHAL']] 
        account_sid = os.environ['TWILIO_ACCOUNT_SID']
        auth_token = os.environ['TWILIO_AUTH_TOKEN']
        client = Client(account_sid, auth_token)
        for phoneNumber in phoneNumbers:
            client.messages.create(body=smsBody, from_=os.environ['TWILIO_PHONE_NUMBER'], to=phoneNumber)
    except Exception as err:
        print('Failed to send sms: ' + str(err))
        return False

    return True


def generateAuthCode(length):
    return ''.join(random.choices(string.digits, k=length))


def generateIdCode(length=5):
    return ''.join(random.choices((string.ascii_uppercase + string.digits), k=length))


def getDateTimeAsString(dt):
    if not dt: 
        return constants.DATETIME_NOT_AVAILABLE
    
    return dt.strftime('%B %d, %H:%M')
