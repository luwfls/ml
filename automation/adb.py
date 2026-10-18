import re
import random
import math
import subprocess
import time

import cv2
import numpy as np


class AdbDevice:
    def __init__(self, serial, executable='adb', timeout=10, cancel=None):
        if not isinstance(serial, str) or not serial.strip():
            raise ValueError('请选择明确的设备 serial')
        self.serial = serial.strip()
        self.executable = executable
        self.timeout = timeout
        self.cancel = cancel

    def run(self, *arguments):
        try:
            command = [self.executable, '-s', self.serial, *map(str, arguments)]
            if self.cancel is None:
                result = subprocess.run(command, capture_output=True, timeout=self.timeout, check=False)
            else:
                if self.cancel.is_set():
                    raise RuntimeError('运行已取消')
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                deadline = time.monotonic() + self.timeout
                try:
                    while True:
                        if self.cancel.is_set():
                            raise RuntimeError('运行已取消')
                        if time.monotonic() >= deadline:
                            raise subprocess.TimeoutExpired(command, self.timeout)
                        try:
                            stdout, stderr = process.communicate(timeout=.05)
                            result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
                            break
                        except subprocess.TimeoutExpired:
                            continue
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate()
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(f'ADB 调用失败: {error}') from error
        if result.returncode:
            raise RuntimeError(result.stderr.decode('utf-8', errors='replace').strip() or 'ADB 执行失败')
        return result.stdout

    def capture(self):
        raw = self.run('exec-out', 'screencap', '-p')
        frame = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError('设备截图不是有效 PNG')
        return frame

    def execute(self, action, match, frame):
        height, width = frame.shape[:2]
        dump = self.run('shell', 'dumpsys', 'input').decode('utf-8', errors='replace')
        viewport = re.search(r'Viewport\s+INTERNAL:.*?logicalFrame=\[0,\s*0,\s*(\d+),\s*(\d+)\].*?isActive=\[1\]',
                             ' '.join(dump.split()))
        if viewport is None or tuple(map(int, viewport.groups())) != (width, height):
            raise RuntimeError('无法确认截图与当前安卓逻辑显示坐标一致，请重新截图或检查设备显示')
        from .state import validate_state
        action = validate_state({'id': 'action', 'recognition': {'type': 'text', 'texts': ['action']}, 'actions': [action]})['actions'][0]
        kind = action['type']
        if kind == 'click_match':
            if match.get('ambiguous') or not match.get('found') or not match.get('bbox'):
                raise RuntimeError('点击需要唯一、有效的识别框')
            left, top, right, bottom = match['bbox']
            if 'click_region' in action:
                a, b, c, d = action['click_region']
                x = random.randrange(math.ceil(a * width), min(width, math.ceil(c * width)))
                y = random.randrange(math.ceil(b * height), min(height, math.ceil(d * height)))
            elif 'target_box' in action:
                from .state import validate_state
                validate_state({'id': 'target', 'recognition': {'type': 'image', 'asset': 'target.png'}, 'actions': [action]})
                a, b, c, d = action['target_box']
                x = int(left + (a + c) / 2 * (right - left))
                y = int(top + (b + d) / 2 * (bottom - top))
            else:
                x = random.randrange(max(0, math.ceil(left)), min(width, math.ceil(right)))
                y = random.randrange(max(0, math.ceil(top)), min(height, math.ceil(bottom)))
            if not 0 <= x < width or not 0 <= y < height:
                raise RuntimeError('点击坐标越界')
            self.run('shell', 'input', 'tap', x, y)
        elif kind == 'key':
            key = action['key'].lower()
            codes = {'back': 4, 'home': 3, 'enter': 66, 'space': 62}
            code = codes[key] if key in codes else 29 + ord(key) - ord('a')
            self.run('shell', 'input', 'keyevent', code)
        elif kind == 'swipe':
            points = action.get('points')
            if points is None:
                half = min(action.get('distance', .6), .9) / 2
                direction = action['direction']
                dx, dy = {'up': (0, -half), 'down': (0, half), 'left': (-half, 0), 'right': (half, 0)}[direction]
                points = [.5 - dx, .5 - dy, .5 + dx, .5 + dy]
            coordinates = [min(size - 1, int(round(value * size))) for value, size in zip(points, [width, height, width, height])]
            self.run('shell', 'input', 'swipe', *coordinates, int(action.get('duration_ms', 300)))
        else:
            raise ValueError('不支持的设备动作')


def list_devices(executable='adb'):
    result = subprocess.run([executable, 'devices', '-l'], capture_output=True, timeout=10, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))
    devices = []
    for line in result.stdout.decode('utf-8', errors='replace').splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            devices.append({'serial': parts[0], 'status': parts[1], 'detail': ' '.join(parts[2:])})
    return devices
