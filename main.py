#!/usr/bin/python3
import base64
import collections
import datetime
import platform
import subprocess
import sys
import time
import wave

import board
from gpiozero import Button
import neopixel
import yaml

import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate("family-transponder-firebase-adminsdk-xr75d-da4523c013.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

pixels = neopixel.NeoPixel(board.D12, 10)
pixels[0] = (0, 0, 0)

RECORDING_CMD = 'arecord -D plughw:1,0 --channels 1 --format S16_LE --rate 16000 --buffer-size 1024 --file-type raw'
PLAYBACK_CMD = 'aplay /tmp/audio.wav'
NORMALIZE_CMD = 'sox --norm /tmp/audio.wav /tmp/sox.wav; mv /tmp/sox.wav /tmp/audio.wav'

Mailbox = collections.namedtuple('Mailbox', ['mailbox_id', 'led_index', 'button'])


class Mailbox:
    def __init__(self, id, fields):
        self.mailbox_id = id
        self.led_index = fields['led_index']
        self.button = Button(fields['button_pin'])

        self.messages_ref = db.collection(u'mailboxes').document(id).collection('messages')
        self.messages_ref.where(u'unread', '==', True).on_snapshot(self.on_messages_snapshot)

        self.messages = []

    def on_messages_snapshot(self, snaps, changes, read_time):
        self.messages = snaps


class MessageClient:
    def __init__(self):
        self.hostname = platform.node()

        self.ref = db.collection(u'hosts').document(self.hostname)

        self.mailboxes = {}

        for mailbox_snap in self.ref.collection('mailboxes').get():
            self.mailboxes[mailbox_snap.id] = Mailbox(mailbox_snap.id, mailbox_snap.to_dict())

    def save_wav(self, wav_path, content):
        w = wave.open(str(wav_path), 'wb')
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(content)
        w.close()
        print('SAVED', wav_path)

    def send_message(self, mailbox):
        print('RECORD', mailbox.mailbox_id)
        to_mailboxes = { mailbox }
        pixels[mailbox.led_index] = (255, 0, 0)

        record_process = subprocess.Popen(
            RECORDING_CMD, shell=True, stdout=subprocess.PIPE)

        data = bytearray()

        while True:
            data.extend(record_process.stdout.read(1024 * 2))

            for other_mailbox in self.mailboxes.values():
                if other_mailbox.button.is_pressed:
                    if not other_mailbox in to_mailboxes:
                        pixels[other_mailbox.led_index] = (255, 0, 0)
                        to_mailboxes.add(other_mailbox)

            if not mailbox.button.is_pressed:
                break

        for _ in range(4):
            data.extend(record_process.stdout.read(1024 * 2))

        record_process.terminate()

        print('UPLOAD', mailbox.mailbox_id)
        for to_mailbox in to_mailboxes:
            pixels[to_mailbox.led_index] = (128, 128, 0)

        batch = db.batch()
        
        audio_ref = db.collection(u'audio').document()
        batch.set(audio_ref, {
            'timestamp': firestore.SERVER_TIMESTAMP,
            'host': self.hostname,
            'format': 'raw_s16le_22khz_mono',
            'samples': bytes(data)
        })
        
        for to_mailbox in to_mailboxes:
            message_ref = db.collection(u'mailboxes').document(to_mailbox.mailbox_id).collection('messages').document()
            batch.set(message_ref, {
                'timestamp': firestore.SERVER_TIMESTAMP,
                'host': self.hostname,
                'unread': True,
                'audio_ref': audio_ref
            })

        batch.commit()

        for to_mailbox in to_mailboxes:
            pixels[to_mailbox.led_index] = (0, 0, 0)

    def playback_message(self, mailbox):
        print('PLAYBACK', mailbox.mailbox_id)

        if len(mailbox.messages) == 0:
            print('EMPTY')
            return

        message = mailbox.messages[0]
        audio = message.get('audio_ref').get().to_dict()

        self.save_wav('/tmp/audio.wav', audio['samples'])
        subprocess.run(NORMALIZE_CMD, shell=True, check=True)
        subprocess.run(PLAYBACK_CMD, shell=True, check=True)

        mailbox.messages_ref.document(message.id).update({
            'unread': False,
        })

    def serve(self):
        print('SERVE')

        while True:
            for mailbox in self.mailboxes.values():
                if mailbox.button.is_pressed:
                    print('INITIATE', mailbox.mailbox_id)

                    start = time.time()
                    while mailbox.button.is_pressed:
                        now = time.time()
                        if now - start > 0.2:
                            break
                    
                    if mailbox.button.is_pressed:
                        print('HELD')
                        self.send_message(mailbox)
                    
                    else:
                        print('SHORT')
                        self.playback_message(mailbox)

                    print('FINISHED')
                
                else:
                    if len(mailbox.messages) > 0:
                        pixels[mailbox.led_index] = (128, 128, 128)
                    else:
                        pixels[mailbox.led_index] = (0, 0, 0)


            time.sleep(0.1)


client = MessageClient()
client.serve()
