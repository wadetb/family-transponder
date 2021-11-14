import pathlib
import time
import board
import neopixel

PIXEL_COUNT = 11

pixels = neopixel.NeoPixel(board.D12, PIXEL_COUNT)
pixels[0] = (0, 0, 0)

#while True:
#print('RED')
#pixels[0] = (128, 0, 0)
#time.sleep(1.1)
#print('GREEN')
#pixels[0] = (0, 128, 0)
#time.sleep(1.1)
#print('BLUE')
#pixels[0] = (0, 0, 128)
#time.sleep(1.1)

signal_file = pathlib.Path('blink_stop')

if signal_file.exists():
    signal_file.unlink()

i = 0
while not signal_file.exists():
    pixels[i] = (128, 128, 128)
    time.sleep(0.1)
    pixels[i] = (0, 0, 0)
    i = (i + 1) % PIXEL_COUNT

for i in range(0, PIXEL_COUNT):
    pixels[i] = (0, 0, 0)

try:
    signal_file.unlink()
except FileNotFoundError:
    pass

