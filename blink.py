import pathlib
import time
import board
import neopixel

pixels = neopixel.NeoPixel(board.D12, 10)
pixels[0] = (0, 0, 0)

signal_file = pathlib.Path('blink_stop')

if signal_file.exists():
    signal_file.unlink()

i = 0
while not signal_file.exists():
    pixels[i] = (128, 128, 128)
    time.sleep(0.1)
    pixels[i] = (0, 0, 0)
    i = (i + 1) % 10

for i in range(0, 10):
    pixels[i] = (0, 0, 0)

try:
    signal_file.unlink()
except FileNotFoundError:
    pass

