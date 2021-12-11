#!/usr/bin/python3
import datetime
import logging
import os
import platform
import subprocess
import threading
import time
import wave
import zlib

import board
from gpiozero import Button
import neopixel
import pygame as pg
#import yappi

import firebase_admin
from firebase_admin import credentials, firestore

def wait():
    time.sleep(0.1)


# def save_wav(wav_path, content):
#     w = wave.open(str(wav_path), 'wb')
#     w.setnchannels(1)
#     w.setsampwidth(2)
#     w.setframerate(16000)
#     w.writeframes(content)
#     w.close()
#     logging.info(f'SAVED {wav_path}')


class Service:
    def __init__(self):
        logging.basicConfig(level=logging.INFO)
        logging.info('STARTUP')

        cred = credentials.Certificate("family-transponder-firebase-adminsdk-xr75d-da4523c013.json")
        firebase_admin.initialize_app(cred)

        self.db = firestore.client()
        self.audio_collection = self.db.collection(u'audio')

        subprocess.run("touch blink_stop", shell=True, check=True)
        time.sleep(1)

        if os.geteuid() == 0:
            self.pixels = neopixel.NeoPixel(board.D12, 20)
        else:
            logging.warning('Not running as root, NeoPixels disabled')
            self.pixels = None # root access required
            
        self.buttons = {}

        pg.mixer.init(16000, -16, 1, 65536)

        self.hostname = platform.node()
        self.quit_requested = False

    def set_pixel(self, index, color):
        if self.pixels is not None:
            self.pixels[index] = color


class Recorder:
    def __init__(self):
        self.mailboxes = set()

        self.thread = threading.Thread(target=self.run)
        self.thread.start()

    def run(self):
        cmd = 'arecord -D plughw:1,0 --channels 1 --format S16_LE --rate 16000 --buffer-size 4096 --file-type raw'

        record_process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)

        while not service.quit_requested:
            data = record_process.stdout.read(4096 * 2)

            for mailbox in self.mailboxes:
                mailbox.recorded.append(data)


class Mailbox:
    def __init__(self, id, fields):
        logging.info(f'MAILBOX {id} {fields}')

        self.mailbox_id = id
        self.led_index = fields['led_index']
        self.pin = 's'

        button_pin = fields['button_pin']
        if not button_pin in service.buttons:
            service.buttons[button_pin] = Button(button_pin)
        self.button = service.buttons[button_pin]

        self.ref = service.db.collection(u'mailboxes').document(id)
        self.watch = self.ref.on_snapshot(self.on_mailbox_snapshot)

        self.messages_ref = self.ref.collection('messages')
        self.messages_watch = self.messages_ref.where(u'unread', '==', True).on_snapshot(self.on_messages_snapshot)
        self.messages = []

        self.recorded = None
        self.last_unlock_time = None

        self.stop_thread = False
        self.thread = threading.Thread(None, self.run)
        self.thread.start()

    def __del__(self):
        logging.info(f'CLOSE {self.mailbox_id}')
        self.watch.unsubscribe()
        self.messages_watch.unsubscribe()
        self.stop_thread = True
        self.thread.join()

    def on_messages_snapshot(self, snaps, changes, read_time):
        logging.info(f'MESSAGES {self.mailbox_id} {len(snaps)}')
        self.messages = snaps
        self.set_led()

    def on_mailbox_snapshot(self, snaps, changes, read_time):
        fields = changes[0].document.to_dict()
        logging.info(f'MAILBOX_SNAPSHOT {self.mailbox_id} {fields}')
        self.pin = fields['pin']

    def still_unlocked(self):
        if self.last_unlock_time is not None:
            time_since_last_unlock = time.time() - self.last_unlock_time
            if time_since_last_unlock < 20:
                return True
        return False

    def check_pin(self):
        logging.info(f'CHECK_PIN {self.mailbox_id} {self.pin}')
        service.set_pixel(self.led_index, (0, 0, 128))

        pin = 's'
        while True:
            logging.info(f'PIN {pin}')
            if pin == self.pin:
                self.last_unlock_time = time.time()
                return True

            start = time.time()
            while not self.button.is_pressed:
                now = time.time()
                if now - start > 2.0:
                    return False
                wait()

            start = time.time()
            press_time = 0
            while self.button.is_pressed:
                wait()

            press_time = time.time() - start

            if press_time >= 0.5:
                pin += 'l'
            else:
                pin += 's'

    def playback_message(self):
        logging.info(f'PLAYBACK {self.mailbox_id}')

        if len(self.messages) == 0:
            logging.info('EMPTY')
            return

        message = self.messages[0]
        audio = message.get('audio_ref').get().to_dict()

#        if audio['format'].contains('zlib'):
#            data = zlib.decompress(audio['samples'])
#        else:
        data = audio['samples']

        #path = f'/tmp/{self.mailbox_id}.wav' 
        #save_wav(path, data)
        #subprocess.run(f'sox --norm {path} {path}.sox.wav', shell=True, check=True)
        #subprocess.run(f'aplay -Dplug:dmix {path}.sox.wav', shell=True, check=True)
        sound = pg.mixer.Sound(data)
        #sound = pg.sndarray.make_sound(data) # needs decoding
        sound.play()

        self.messages_ref.document(message.id).update({
            'unread': False,
        })

        time.sleep(sound.get_length())

    def upload(self, data):
        start = time.time()
        #yappi.start()
        logging.info(f'UPLOAD {self.mailbox_id}')

        #compressed = zlib.compress(data)
        compressed = data

        logging.info(f'COMPRESS {len(data)} -> {len(compressed)}')

        batch = service.db.batch()
        
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        audio_ref = service.audio_collection.document()
        message_ref = self.messages_ref.document()

        batch.set(audio_ref, {
            'timestamp': timestamp, #firestore.SERVER_TIMESTAMP,
            'host': service.hostname,
            'format': 'raw_s16le_16100_mono',
            'samples': compressed
        })
        batch.set(message_ref, {
            'timestamp': timestamp, #firestore.SERVER_TIMESTAMP,
            'host': service.hostname,
            'unread': True,
            'audio_ref': audio_ref
        })
        
        batch.commit()
        
        logging.info(f'UPLOAD_COMPLETE {self.mailbox_id} {time.time() - start}')
        #yappi.stop()
        #yappi.get_func_stats().print_all()
        #yappi.get_func_stats().save('upload.callgrind', type='callgrind')

    def send_message(self):
        logging.info(f'RECORD {self.mailbox_id}')
        service.set_pixel(self.led_index, (255, 0, 0))

        self.recorded = []
        recorder.mailboxes.add(self)

        while self.button.is_pressed:
            wait()
        time.sleep(0.5) # drain buffers

        recorder.mailboxes.remove(self)

        data = b''.join(self.recorded)
        self.recorded = None

        upload_thread = threading.Thread(target=self.upload, args=(data,))
        upload_thread.start()

    def run(self):
        logging.info(f'RUN {self.mailbox_id}')

        hold_start = None

        while not self.stop_thread and not service.quit_requested:

            button_pressed = self.button.is_pressed

            if button_pressed:
                if hold_start is None:
                    logging.info(f'BUTTON {self.mailbox_id}')
                    hold_start = time.time()

                else:
                    hold_duration = time.time() - hold_start
                    if hold_duration > 0.5:
                        logging.info(f'HELD {hold_duration}')
                        self.send_message()
                        self.set_led()

            else:
                if hold_start is not None:
                    if self.check_pin():
                        self.playback_message()
                    self.set_led()
                hold_start = None

            
            wait()

        logging.info(f'STOP {self.mailbox_id}')

    def set_led(self):
        if len(self.messages) > 0:
            service.set_pixel(self.led_index, (128, 128, 128))
        else:
            service.set_pixel(self.led_index, (0, 0, 0))


class MessageClient:
    def __init__(self):
        self.need_restart = False
        self.mailboxes = {}

        self.ref = service.db.collection(u'hosts').document(service.hostname)
        self.ref.collection('mailboxes').on_snapshot(self.on_mailboxes)

        service.db.collection('global').document('version').on_snapshot(self.on_version)

    def on_mailboxes(self, snap, changes, read_time):
        for change in changes:
            if change.type.name == 'ADDED':
                # if change.document.id in ['simon']:
                    self.mailboxes[change.document.id] = Mailbox(change.document.id, change.document.to_dict())
            elif change.type.name == 'MODIFIED':
                del self.mailboxes[change.document.id]
                self.mailboxes[change.document.id] = Mailbox(change.document.id, change.document.to_dict())
            elif change.type.name == 'REMOVED':
                del self.mailboxes[change.document.id]

    def on_version(self, snaps, changes, read_time):
        latest_version = snaps[0].get('version')
        cmd = 'git describe --always'
        local_version = subprocess.check_output(cmd, shell=True).decode().strip()
        logging.info(f'LATEST_VERSION {latest_version} vs {local_version}')

        if latest_version != local_version:
            logging.info(f'OTA_UPGRADE {latest_version}')
            subprocess.run('git fetch', shell=True)
            subprocess.run(f'git checkout {latest_version}', shell=True)
            self.need_restart = True


if __name__ == "__main__":
    service = Service()
    recorder = Recorder()
    client = MessageClient()

    while not client.need_restart:
        time.sleep(1.0)

    service.quit_requested = True
