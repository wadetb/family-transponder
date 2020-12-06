#!/usr/bin/python3
import base64
import collections
import datetime
import json
import pathlib
import platform
import subprocess
import sys
import time
from time import sleep
import wave

from gpiozero import LED, Button
import paho.mqtt.client as mqtt
import yaml


Person = collections.namedtuple('Person', ['name', 'led', 'button'])


class Config:
    def __init__(self, path):
        self.load(path)

    def load(self, path):
        with open(path) as config_file:
            self.fields = yaml.safe_load(config_file)

        hostname = platform.node()
        if hostname in self.fields:
            self.fields.update(self.fields[hostname])

    def __getattr__(self, key):
        return self.fields[key]


class MessageClient:
    def __init__(self):
        self.config = Config('config.yaml')
        self.state = {'mode': 'idle', 'suggestions': []}

        self.client = mqtt.Client()

        self.people = [Person(p['name'], LED(p['led_pin']), Button(p['button_pin'])) for p in self.config.people]


    def on_connect(self, _client, _userdata, _flags, rc):
        print('CONNECT', rc)
        self.client.subscribe('km/{}'.format(self.config.myself))

    def on_message(self, _client, _userdata, msg):
        packet = json.loads(msg.payload.decode())
        print('RECV', msg.topic, json.dumps(packet)[:100])
        if packet['code'] == 'message':
            recording_path = self.encode_path(datetime.datetime.now(), packet['from'], self.config.myself)
            data = base64.b64decode(packet['buffer'])
            self.save_wav(recording_path, bytes(data))

    def send(self, to, packet):
        topic = 'km/{}'.format(to)
        print('SEND', topic, json.dumps(packet)[:100])
        self.client.publish(topic, json.dumps(packet))

    def encode_path(self, timestamp, person_from, person_to):
        return pathlib.Path(self.config.recordings_dir) / f'{timestamp:%Y%m%d%H%M%S}-from-{person_from}-to-{person_to}.wav'

    def save_wav(self, wav_path, content):
        w = wave.open(str(wav_path), 'wb')
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(content)
        w.close()
        print('SAVED', wav_path)

    def send_message(self, person):
        print('START_RECORDING', person.name)
        record_process = subprocess.Popen(
            self.config.recording_cmd, shell=True, stdout=subprocess.PIPE)

        data = bytearray()

        while True:
            data.extend(record_process.stdout.read(1024 * 2))
            if not person.button.is_pressed:
                print('BUTTON_RELEASED')
                break

        for _ in range(4):
            # print('GET_EXTRA')
            data.extend(record_process.stdout.read(1024 * 2))

        record_process.terminate()

        recording_path = self.encode_path(datetime.datetime.now(), self.config.myself, person.name)
        self.save_wav(recording_path, bytes(data))

        normalize_cmd = self.config.normalize_cmd.replace('$wav_path', str(recording_path))
        subprocess.run(normalize_cmd, shell=True, check=True)

        # playback_cmd = self.config.playback_cmd.replace('$wav_path', str(recording_path))
        # subprocess.run(playback_cmd, shell=True, check=True)

        self.send(person.name, {'code': 'message', 'from': self.config.myself, 'buffer': base64.b64encode(bytes(data)).decode('ascii')})

    def serve(self):
        print('STARTUP')

        print('CONNECTING', self.config.mqtt_url)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.connect(self.config.mqtt_url[7:-1])
        self.client.loop_start()

        while True:
            for person in self.people:
                if person.button.is_pressed:
                    print('BUTTON_PRESSED', person.name)
                    person.led.on()
                    print('LED_ON', person.name)
                    self.send_message(person)
                    person.led.off()
                    print('LED_OFF', person.name)

            time.sleep(0.1)


client = MessageClient()
client.serve()
