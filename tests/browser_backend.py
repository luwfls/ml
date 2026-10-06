"""Foreground browser-test fixture; never connects to an actual Android device."""
import argparse
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation import web
from automation.state import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    args.data.mkdir(parents=True, exist_ok=True)
    image = np.full((480, 640, 3), 242, np.uint8)
    cv2.rectangle(image, (120, 100), (350, 210), (80, 130, 40), -1)
    cv2.putText(image, 'CONFIRM', (142, 164), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    cv2.rectangle(image, (410, 300), (570, 380), (100, 80, 150), -1)
    cv2.putText(image, 'NEXT', (440, 350), cv2.FONT_HERSHEY_SIMPLEX, .8, (255, 255, 255), 2)
    if not cv2.imwrite(str(args.data / 'browser-page.png'), image):
        raise RuntimeError('Could not write browser fixture')

    class FakeDevice:
        def __init__(self, serial, executable='adb', **kwargs):
            if not isinstance(serial, str) or not serial.strip():
                raise ValueError('请选择明确的设备 serial')
            self.serial = serial.strip()

        def capture(self):
            return image.copy()

        def execute(self, action, match, frame):
            with (args.data / 'fake-actions.log').open('a', encoding='utf-8') as log:
                log.write(str(action) + '\n')

    web.AdbDevice = FakeDevice
    web.list_devices = lambda adb: [{'serial': 'browser-device', 'status': 'device'}]
    server = web.create_server(Store(args.data), args.port)
    print(f'Browser fixture ready on {server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop_runs()
        server.server_close()


if __name__ == '__main__':
    main()
