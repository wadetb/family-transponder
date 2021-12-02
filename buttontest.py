from gpiozero import Button
from time import sleep

buttons = [(i, Button(i)) for i in range(27)]

while True:
    for button_index, button in buttons:
        if button.is_pressed:
            print(f'{button_index} is pressed!')
    sleep(0.1)

