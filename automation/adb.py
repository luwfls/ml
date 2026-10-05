import re
import subprocess

import cv2
import numpy as np


class AdbDevice:
    def __init__(self, serial, executable='adb', timeout=10):
        if not isinstance(serial, str) or not serial.strip():
            raise ValueError('请选择明确的设备 serial')
        self.serial = serial.strip()
        self.executable = executable
        self.timeout = timeout

    def run(self, *arguments):
        try:
            result = subprocess.run([self.executable, '-s', self.serial, *map(str, arguments)],
                                    capture_output=True, timeout=self.timeout, check=False)
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
        kind = action['type']
        if kind == 'click_match':
            if match.get('ambiguous') or not match.get('found') or not match.get('bbox'):
                raise RuntimeError('点击需要唯一、有效的识别框')
            left, top, right, bottom = match['bbox']
            x, y = int((left + right) / 2), int((top + bottom) / 2)
            if not 0 <= x < width or not 0 <= y < height:
                raise RuntimeError('点击坐标越界')
            self.run('shell', 'input', 'tap', x, y)
        elif kind == 'key':
            self.run('shell', 'input', 'keyevent', {'back': 4, 'home': 3, 'enter': 66}[action['key']])
        elif kind == 'swipe':
            coordinates = [min(size - 1, int(value * size)) for value, size in zip(action['points'], [width, height, width, height])]
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
