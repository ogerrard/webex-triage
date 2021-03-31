"""
TODO:   Update SQL to SQLAlchemy rather than direct SQL statements
        Split out functions for modularity.
        Implement Testing.
        Allow more customisation through .env or passing arguments.
"""


"""importing all modules needed"""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Dict, Any, AnyStr
import requests
import json
import datetime
import os
import time
import sqlite3

from dotenv import load_dotenv
from loguru import logger
from webexteamssdk import WebexTeamsAPI, ApiError


"""Defining the classes for the incoming API requests from Webex"""
class Message(BaseModel):
    id: str
    name: str
    targetUrl: str
    resource: str
    event: str
    filter: Optional[str] = None
    orgId: str
    createdBy: str
    appId: str
    ownedBy: str
    status: str
    created: str
    actorId: str
    data: dict

class CardResponse(BaseModel):
    id: str
    name: str
    targetUrl: str
    resource: str
    event: str
    filter: Optional[str] = None
    orgId: str
    createdBy: str
    appId: str
    ownedBy: str
    status: str
    created: str
    actorId: str
    data: dict



"""Import and set the environemnt variables from the '.env' file"""
load_dotenv()
WEBHOOKURL = os.getenv("TEAMS_BOT_URL")
logger.debug(WEBHOOKURL)
BOTEMAIL = os.getenv("TEAMS_BOT_EMAIL")
TEAMSTOKEN = os.getenv("WEBEX_TEAMS_ACCESS_TOKEN")
DOCTORSROOM = os.getenv("DOCTORS_ROOM")
DATABASE = os.getenv("DATABASE_NAME")

""" Variables to decide the time to wait for a response before sending another alert and how many alerts to be sent before
    falling back"""
TIMEOUTSECONDS = 7
ALERTCOUNT = 5

""" FastAPI and Webex Connections"""
app = FastAPI()
api = WebexTeamsAPI(access_token=TEAMSTOKEN)


"""Connect to SQLite3 Database and check for the table - create if it doesn't exist."""
con = sqlite3.connect(DATABASE, check_same_thread=False)
cur = con.cursor()
cur.execute('''CREATE TABLE IF NOT EXISTS webexTriage
               (card_id text, type text, sender_id text, sender_name text, clicked text, responder_id text, responder_name text, room_id text)''')


""" Define the triggers for the bot to listen to - needs to be built out further
    defining the necessary Global Variables"""
triggers = ["help", "emergency", "support", "assistance", "hlep", "emergence", "assist"]
ROOMSLIST = {""}
MESSAGEWEBHOOKURL = f'{WEBHOOKURL}/messages'
ATTACHMENTWEBHOOKURL = f'{WEBHOOKURL}/cards'


@app.post("/messages")
def read_message(item: Message):
    """
    Defining the actions for the incoming POST request to the messages URL.
    Sets the incoming message ID and sender ID before running the flow to get the messages
    details and run the rest of the flow accordingly

    :param Message: Class for the response format to the messages URL.
    """

    message_id = item.data["id"]
    sender_id = item.data["personId"]
    sender = get_person(sender_id)
    sender_name = sender.displayName
    get_message(message_id, sender_name)
    return

@app.post("/cards")
async def read_message(item: CardResponse):
    """
    Defining the actions for the incoming POST request to the cards URL.
    Sets the incoming person ID, card ID and room ID. Checks the card against
    the database for existence and then either cleans up the room or creates the 
    room
    
    :param CardResponse: Class for the response format to the cards URL.
    """
    person_id = item.data["personId"]
    card_id = item.data["messageId"]
    room_id = item.data["roomId"]
    cur.execute("""SELECT card_id
                   FROM webexTriage
                   WHERE card_id=?""",
                (card_id,))
    result = cur.fetchone()
    if result:
        cur.execute('''UPDATE webexTriage
                SET clicked =?
                WHERE card_id=?''', ('1', card_id,))
    # Retrieve information about the sender
    person = get_person(person_id)
    # Trigger Teams room creation flow
    if room_id in ROOMSLIST:
        logger.info("Triggering clean up for room.")
        clean_up(room_id)
    else:
        create_room(card_id, person)
        return

def check_webhooks():
    """ Check the existing webhooks and update/create them accordingly"""
    try:
        webhooks = api.webhooks.list()
    except ApiError as e:
        logger.error(e)
    webhooks_list = list(webhooks)
    webhookCount = len(webhooks_list)
    logger.info(f'Webhook count is: {webhookCount}')
    if webhookCount == 0:
        try:
            api.webhooks.create("Message Webhook", MESSAGEWEBHOOKURL, "messages", "created")
        except ApiError as e:
            logger.error(e)
        try:
            api.webhooks.create("Card Attachment Webhook", ATTACHMENTWEBHOOKURL, "attachmentActions", "created")
        except ApiError as e:
            logger.error(e)

    if webhookCount == 1:
        for webhook in webhooks:
            if "messages" in webhook.resource:
                if "created" in webhook.event:
                    logger.info("Existing Webhook is not Messages Webhook.")
                    logger.info("Creating Messages Webhook.")
                    try:
                        api.webhooks.create("Message Webhook", MESSAGEWEBHOOKURL, "messages", "created")
                    except ApiError as e:
                        logger.error(e)
            if "attachmentActions" in webhook.resource:
                if "created" in webhook.event:
                    logger.info("Existing Webhook is not Messages Webhook.")
                    logger.info("Creating Messages Webhook.")
                    try:
                        api.webhooks.create("Card Attachment Webhook", ATTACHMENTWEBHOOKURL, "attachmentActions", "created")
                    except ApiError as e:
                        logger.error(e)
    else:
        for webhook in webhooks:
            if ("messages" in webhook.resource) and ("created" in webhook.event):
                webhook_id = webhook.id
                try:
                    api.webhooks.update(webhook_id, "Message Webhook", MESSAGEWEBHOOKURL)
                    logger.info("Updated Message Webhook")
                except ApiError as e:
                    logger.error(e)

            if ("attachmentActions" in webhook.resource) and ("created" in webhook.event):
                webhook_id = webhook.id
                try:
                    api.webhooks.update(webhook_id, "Card Attachment Webhook", ATTACHMENTWEBHOOKURL)
                    logger.info("Updated Attachment Webhook")
                except ApiError as e:
                    logger.error(e)

def get_message(message_id, sender_name):
    """
    Get the details of a message, check:
    if the sender was the bot then ignore;
    if the sender wasn't the bot and it contains a trigger word, then run the emergency function
        
    :param message_id: the ID of the message to retrieve
    :param sender_name: the name of the person who sent the message
    """
    try:
        message_data = api.messages.get(message_id)
        message = message_data.text
        sender = message_data.personEmail
        sender_id = message_data.personId
        logger.info(f'{sender} sent {message}')
        if sender == BOTEMAIL:
            logger.info("Ignoring our own message")
        elif any(word in message.lower() for word in triggers):
            logger.info("Emergency Detected - Running Script.")
            markdown = "We've received your emergency request... matching with a doctor. Sit tight."
            reply(sender, markdown)
            send_card(sender_id, sender_name)
    except ApiError as e:
        logger.error(e)
    
def get_person(person_id):
    """
    Retrieve the details of a person based on ID.

    :param person_id: ID of the person
    :returns: object with all information fof a person from Webex API
    """
    try:
        logger.info("Getting Person Details.")
        data = api.people.get(person_id)
        return data
    except ApiError as e:
        logger.error(e)

def reply(sender, markdown):
    """
    Function to send a reply.

    :param sender: email of the person who is being sent a message
    :param markdown: Markdown formatted message to be sent.
    """
    try:
        api.messages.create(toPersonEmail=sender, markdown=markdown)
        logger.info(f'Sending response to {sender}')
    except ApiError as e:
        logger.error(e)

def send_card(sender_id, sender_name):
    """
    Sending a card to the pre-defined doctors room.
    Also updates the database as required with information about the card.
    Also sends the updates to the Doctors space if there is no response in the set time
    
    :param sender_id: ID of the person who sent the initial message.
    :param sender_name: Name od the person who sent the initial message.
    """
    current_DT = datetime.datetime.now()
    current_DT = current_DT.strftime("%H:%M")
    try:
        card = [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "type": "AdaptiveCard",
                        "version": "1.0",
                        "body": [
                                    {
                                        "type": "TextBlock",
                                        "text": "Incoming Request",
                                        "size": "ExtraLarge",
                                        "color": "Warning",
                                        "weight": "Bolder"
                                    },
                                    {
                                        "type": "TextBlock",
                                        "text": f"New request incoming from {sender_name}",
                                        "size": "Medium",
                                        "weight": "Bolder"
                                    },
                                    {
                                        "type": "TextBlock",
                                        "text": f"Request sent at {current_DT}",
                                        "spacing": "ExtraLarge",
                                        "size": "Medium"
                                    },
                                    {
                                        "type": "ActionSet",
                                        "actions": [
                                            {
                                                "type": "Action.Submit",
                                                "title": "Click to Accept",
                                                "id": ""
                                            }
                                        ]
                                    }
                                ],
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    },
                }
            ]

        card_res = api.messages.create(roomId=DOCTORSROOM, markdown="Card sent.", attachments=card )
        card_id = card_res.id
        cur.execute("INSERT into webexTriage (card_id, type, sender_id, sender_name, clicked) VALUES (?, ?, ?, ?, ?)", (card_id, "request" , sender_id, sender_name, "0"))
        con.commit()
        message_count = 1
        global CARDCLICKED
        cur.execute("SELECT clicked FROM webexTriage WHERE card_id=?", (card_id,))
        CARDCLICKED = cur.fetchone()
        CARDCLICKED = CARDCLICKED[0]
        while CARDCLICKED == '0':
            if message_count < ALERTCOUNT:
                message = f'<@all> Waiting for a response, mentioning all doctors attempt number {message_count}'
                logger.debug(f"Message attempt {message_count}")
                api.messages.create(roomId=DOCTORSROOM, parentId=card_id, markdown=message)
            else:
                time.sleep(2)
                CARDCLICKED = True
                logger.debug("Max attempts reached, messaging responder.")
                message = f"Request timed out. Sending direct contact details for on-call doctors to {sender_name}"
                api.messages.create(roomId=DOCTORSROOM, parentId=card_id, markdown=message)
                message_responder(sender_id)
                message = f"This request can still be accepted after the timeout, but the requester may already have assistance."
                api.messages.create(roomId=DOCTORSROOM, parentId=card_id, markdown=message)
            message_count += 1
            time.sleep(TIMEOUTSECONDS)
    except ApiError as e:
        logger.error(e)

def send_clean_up(room_id):
    """
    Function to send a card to a room to request post conversation action (currently to delete the space and clean up).

    :param room_id: ID of the room for the card to be sent to
    """
    try:
        card = [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "type": "AdaptiveCard",
                        "version": "1.0",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": "When you've finished in this space, click the button below to clean up and delete this room.",
                                "wrap": True,
                            },
                            {
                                "type": "ActionSet",
                                "actions": [
                                    {"type": "Action.Submit", "title": "Clean Up!"}
                                ],
                            },
                        ],
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    },
                }
            ]
        api.messages.create(roomId=room_id, markdown="Clean up sent.", attachments=card)
    except ApiError as e:
        logger.error(e)

def create_room(card_id, actionClicker):
    """ 
    Create the room which the person requesting assistance as well as the doctor who responded will be added.
    The room name will be in the format '{Current Date and Time} - {Sender Name} & {Responder Name}'
    Database also updated accordingly.

    (Long function which probably needs breaking up)

    :param card_id: ID of the card which was accepted to trigger the room creation.
    :param actionClicker: object with the Webex information of the person who accepted the card.
    """
    try:
        current_DT = datetime.datetime.now()
        current_DT = current_DT.strftime("%Y-%m-%d %H:%M")
        responder_name = actionClicker.displayName
        responder_id = actionClicker.id
        logger.debug(f'responder_id: {responder_id}')
        cur.execute("SELECT sender_name FROM webexTriage WHERE card_id=?", (card_id,))
        sender_name = cur.fetchone()
        sender_name = sender_name[0]
        logger.debug(f"sender_name: {sender_name}")
        cur.execute("SELECT sender_id FROM webexTriage WHERE card_id=?", (card_id,))
        sender_id = cur.fetchone()
        sender_id = sender_id[0]
        logger.debug(f"sender_id: {sender_id}")
        cur.execute("UPDATE webexTriage SET responder_name = ?,responder_id = ? WHERE card_id=?", (card_id, responder_name, responder_id))
        con.commit()
        title = str(f'{current_DT} - {sender_name} & {responder_name}')
        room_res = api.rooms.create(title)
        room_id = room_res.id
        # Add room_id to shelve
        cur.execute(''' UPDATE webexTriage
                SET room_id = ?
                WHERE card_id=?''', (card_id, room_id,))
        con.commit()
        ROOMSLIST.add(room_id)
        try:
            api.memberships.create(room_id, personId=responder_id)
            logger.info(f'Added {responder_name} to space.')
        except ApiError as e:
            memberships = api.memberships.list(roomId=room_id)
            for membership in memberships:
                if membership.personId == responder_id:
                    logger.error("Person is already in the space.")
                    logger.error(e)
                    break
        try:
            api.memberships.create(room_id, personId=sender_id)
            logger.info(f'Added {sender_name} to space.')
        except ApiError as e:
            memberships = api.memberships.list(roomId=room_id)
            for membership in memberships:
                if membership.personId == sender_id:
                    logger.error("Person is already in the space.")
                    logger.error(e)
                    break
        send_clean_up(room_id)
        message = f'{responder_name} has accepted this job. Message will be deleted shortly.'
        api.messages.create(roomId=DOCTORSROOM, parentId=card_id, markdown=message)
        api.messages.delete(card_id)
        cur.execute(''' UPDATE webexTriage
                SET clicked = 1
                WHERE card_id=?''', (card_id,))
        con.commit()
        logger.debug('Deleting Database entry.')
        cur.execute("DELETE from webexTriage WHERE card_id=?", (card_id,))
    except ApiError as e:
        logger.error(e)

def clean_up(room_id):
    """
    Function to clean up the room

    :param room_id: ID of the room to be cleaned up.
    """
    try:
        api.rooms.delete(room_id)
        logger.info("Space has been cleaned up.")
        ROOMSLIST.remove(room_id)
        logger.info("Room purged from list.")
    except ApiError as e:
        logger.error(e)

def message_responder(sender_id):
    """
    Function to send a message to the person requesting assistance after the timeout has occurred.
    Currently sends a card with static data ot the requester.
    
    :param sender_id: ID of the person who requested assistance initiall, who will be receiving the timeout response.
    """
    try:
        logger.debug("Sending contact info to responder after timeout.")
        card = [
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": {
                            "type": "AdaptiveCard",
                            "version": "1.0",
                            "body": [
                            {
                                "type": "TextBlock",
                                "text": "Doctor Contact Information",
                                "size": "Large",
                                "weight": "Bolder",
                                "color": "Attention"
                            },
                            {
                                "type": "TextBlock",
                                "text": "No doctors were available to accept the request within the time.  Here are the direct contacts for the currently on-call doctors:",
                                "wrap": True,
                                "weight": "Bolder"
                            },
                            {
                                "type": "ColumnSet",
                                "columns": [
                                    {
                                        "type": "Column",
                                        "width": "stretch",
                                        "items": [
                                            {
                                                "type": "TextBlock",
                                                "text": "Dr. Ashutosh",
                                                "size": "Large",
                                                "horizontalAlignment": "Center"
                                            }
                                        ]
                                    },
                                    {
                                        "type": "Column",
                                        "width": "stretch",
                                        "items": [
                                            {
                                                "type": "ActionSet",
                                                "actions": [
                                                    {
                                                        "type": "Action.OpenUrl",
                                                        "title": "Call",
                                                        "url": "https://cutt.ly/sk5GhLn"
                                                    }
                                                ],
                                                "spacing": "None",
                                                "horizontalAlignment": "Center"
                                            }
                                        ]
                                    }
                                ],
                            },
                            {
                                "type": "ColumnSet",
                                "columns": [
                                    {
                                        "type": "Column",
                                        "width": "stretch",
                                        "items": [
                                            {
                                                "type": "TextBlock",
                                                "text": "Dr. Ollie",
                                                "size": "Large",
                                                "horizontalAlignment": "Center"
                                            }
                                        ]
                                    },
                                    {
                                        "type": "Column",
                                        "width": "stretch",
                                        "items": [
                                            {
                                                "type": "ActionSet",
                                                "actions": [
                                                    {
                                                        "type": "Action.OpenUrl",
                                                        "title": "Call",
                                                        "url": "https://cutt.ly/bk5Gx4n"
                                                    }
                                                ],
                                                "horizontalAlignment": "Center"
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                "type": "ColumnSet",
                                "columns": [
                                    {
                                        "type": "Column",
                                        "width": "stretch",
                                        "items": [
                                            {
                                                "type": "TextBlock",
                                                "text": "Dr. Patrick",
                                                "size": "Large",
                                                "horizontalAlignment": "Center"
                                            }
                                        ]
                                    },
                                    {
                                        "type": "Column",
                                        "width": "stretch",
                                        "items": [
                                            {
                                                "type": "ActionSet",
                                                "actions": [
                                                    {
                                                        "type": "Action.OpenUrl",
                                                        "title": "Call",
                                                        "url": "https://cutt.ly/Rk5GEzL"
                                                    }
                                                ],
                                                "horizontalAlignment": "Center"
                                            }
                                        ]
                                    }
                                ]
                            }
                        ],
                            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        },
                    }
                ]

        # Actually send the card
        api.messages.create(toPersonId=sender_id, markdown="Card sent.", attachments=card)
    except ApiError as e:
        logger.error(e)

"""Run check webhooks when the script first starts"""
check_webhooks()