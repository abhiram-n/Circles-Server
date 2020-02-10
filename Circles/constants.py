TOKEN_EXPIRATION = 6000000

# Timezone for registering created/update times
TIMEZONE_KOLKATA = 'Asia/Kolkata'
DATETIME_NOT_AVAILABLE = "N/A"

STATUS_OK = 200
STATUS_BAD_REQUEST = 400
STATUS_UNAUTHORIZED = 401
STATUS_NOT_ALLOWED = 405
STATUS_CONFLICT_ERROR = 409
STATUS_GONE = 410
STATUS_PRECONDITION_FAILED = 412
STATUS_SERVER_ERROR = 500

EARNINGS_FACTOR = 0.2
MIN_EARNINGS = 50
NUM_NOTIFICATIONS_TO_SEND = 20

# Request status codes
ACCESS_REQUEST_CANCELLED = -1
ACCESS_REQUEST_UNACCEPTED = 0
ACCESS_REQUEST_ACCEPTED = 1
ACCESS_REQUEST_FULFILLED = 2
ACCESS_REQUEST_REJECTED = 3
ACCESS_REQUEST_VALIDATED = 4
ACCESS_REQUEST_INVALIDATED = 5
ACCESS_REQUEST_NOTIFICATION_TYPE = "ar"
ACCESS_REQUEST_NOTIFICATION_TITLE = "New card request from {}"
ACCESS_REQUEST_NOTIFICATION_BODY = "{} wants to use {} you own for a purchase"
ACCESS_REQUEST_ACCEPTED_TITLE = "{} accepted your card access request"
ACCESS_REQUEST_DECLINED_TITLE = "{} declined your card access request"
ACCESS_REQUEST_ACCEPTED_BODY = "Click to open the request"
ACCESS_REQUEST_DECLINED_BODY = "Click to open the request"

# Posts
POST_NOTIFICATION_TYPE = "post"
POST_NOTIFICATION_TITLE = "New post from {}"
POST_NOTIFICATION_BODY = "{} just beamed a new message to their Circle."

# auth code status
CODE_VERIFICATION_FAILED = 0
CODE_VERIFICATION_SUCCEEDED = 1
CODE_VERIFICATION_EXPIRED = -1
AUTH_CODE_LENGTH = 5

# friend request status codes
FRIEND_REQUEST_ACTIVE = 0
FRIEND_REQUEST_DECLINED = -1
FRIEND_REQUEST_ACCEPTED = 1
FRIEND_REQUEST_NOTIFICATION_TYPE = "fr"
FRIEND_REQUEST_NOTIFICATION_TITLE = "New Friend Request"
FRIEND_REQUEST_NOTIFICATION_BODY = "{} wants to add you to their Circle"
FRIEND_REQUEST_ACCEPTED_TITLE = "{} accepted your request"
FRIEND_REQUEST_DECLINED_TITLE = "{} declined your request"
FRIEND_REQUEST_ACCEPTED_BODY = "You've been added to each other's Circles"
FRIEND_REQUEST_DECLINED_BODY = "You'll remain outside each other's Circles"

# notification constants
FIREBASE_CHANNEL = "circlesWay" # todo

CHAT_NOTIFICATION_TITLE = "New message from {}"
CHAT_NOTIFICATION_BODY = "You have new messages in your encrypted chat"

# user ids
ABHIRAM_USER_ID = 24
ANCHAL_USER_ID = 26

CARD_TYPE_TAG = "Tag"