from Circles import constants
from Circles.models import db, Card
from flask import jsonify, request
from . import apiBlueprint

@apiBlueprint.route("/card/all", methods=['GET'])
def getAllCards():
    db.create_all()
    allCards = Card.query.all()
    listCards = {'cards': []}
    for card in allCards:
        listCards['cards'].append({"name": card.name, "id": card.id})
    db.session.close()
    return jsonify(listCards), constants.STATUS_OK


@apiBlueprint.route("/card/filter", methods=['GET'])
def getCards():
    if "type" not in request.args:
        print("Type is a required paramter for this operation.")
        return "", constants.STATUS_BAD_REQUEST

    objectType = request.args["type"]
    db.create_all()
    allCards = Card.query.filter(Card.objectType == objectType)
    listCards = {'cards': []}
    for card in allCards:
        listCards['cards'].append({"name": card.name, "id": card.id})
    db.session.close()
    return jsonify(listCards), constants.STATUS_OK
