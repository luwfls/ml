import copy
import json
import math
import re
from pathlib import Path


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value):
        raise ValueError('ID 必须由 1–80 个英文字母、数字、下划线或短横线组成')
    return value


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'数值必须在 {low} 到 {high} 之间')
    return value


def validate_state(data):
    if not isinstance(data, dict):
        raise ValueError('State 必须是对象')
    data = copy.deepcopy(data)
    identifier(data.get('id'))
    data.setdefault('name', data['id'])
    data.setdefault('role', 'normal')
    if data['role'] not in {'normal', 'success', 'failure', 'fallback'}:
        raise ValueError('无效 State role')
    data.setdefault('priority', 0)
    number(data['priority'], -10000, 10000)
    recognition = data.get('recognition', {})
    if not isinstance(recognition, dict):
        raise ValueError('recognition 必须是对象')
    if recognition.get('type') == 'image':
        if 'texts' in recognition or not isinstance(recognition.get('asset'), str):
            raise ValueError('图片 State 只配置 asset，不配置 texts')
        identifier(Path(recognition['asset']).stem)
        if recognition['asset'] != Path(recognition['asset']).name or not recognition['asset'].endswith('.png'):
            raise ValueError('asset 必须是资源目录内的 PNG 文件名')
        number(recognition.setdefault('threshold', .85), .01, 1)
        scales = recognition.setdefault('scales', [1.0])
        if not isinstance(scales, list) or not 1 <= len(scales) <= 20:
            raise ValueError('scales 必须是非空列表，最多 20 项')
        for scale in scales:
            number(scale, .1, 5)
    elif recognition.get('type') == 'text':
        texts = recognition.get('texts')
        if 'asset' in recognition or not isinstance(texts, list) or not texts or not all(isinstance(t, str) and t.strip() for t in texts):
            raise ValueError('文字 State 必须配置非空 texts，不能配置 asset')
        mode = recognition.setdefault('mode', 'exact')
        if mode not in {'exact', 'contains', 'fuzzy'}:
            raise ValueError('无效文字匹配模式')
        if mode == 'fuzzy' and any(len(t.strip()) < 3 for t in texts):
            raise ValueError('短文案不能使用模糊匹配')
        number(recognition.setdefault('similarity_threshold', .85), .01, 1)
        number(recognition.setdefault('min_confidence', .8), 0, 1)
    else:
        raise ValueError('识别类型必须为 image 或 text')
    region = recognition.setdefault('region', [0, 0, 1, 1])
    if not isinstance(region, list) or len(region) != 4:
        raise ValueError('ROI 必须是四个归一化坐标')
    for coordinate in region:
        number(coordinate, 0, 1)
    if region[0] >= region[2] or region[1] >= region[3]:
        raise ValueError('ROI 不能为空')
    actions = data.setdefault('actions', [])
    if not isinstance(actions, list):
        raise ValueError('actions 必须是列表')
    for action in actions:
        if not isinstance(action, dict) or action.get('type') not in {'click_match', 'swipe', 'key', 'wait'}:
            raise ValueError('无效动作；首版支持 click_match/swipe/key/wait')
        if action['type'] == 'key' and action.get('key') not in {'back', 'home', 'enter'}:
            raise ValueError('按键支持 back/home/enter')
        if action['type'] == 'wait':
            number(action.get('ms', 500), 0, 10000)
        if action['type'] == 'swipe':
            points = action.get('points')
            if not isinstance(points, list) or len(points) != 4:
                raise ValueError('swipe 需要四个归一化 points 坐标')
            for point in points:
                number(point, 0, 1)
            number(action.get('duration_ms', 300), 1, 10000)
    inputs = [i for i, action in enumerate(actions) if action['type'] != 'wait']
    if len(inputs) > 1 or (inputs and inputs[0] != 0):
        raise ValueError('首版每个 State 最多一个输入动作，等待只能放在输入之后；后续操作由新截图驱动')
    if data['role'] in {'success', 'failure'} and actions:
        raise ValueError('首版成功/失败 State 只作为断言，请保持 actions 为空')
    conditions = data.setdefault('conditions', {})
    if not isinstance(conditions, dict):
        raise ValueError('conditions 必须是对象')
    for key in ['required_states', 'excluded_states']:
        references = conditions.setdefault(key, [])
        if not isinstance(references, list):
            raise ValueError('条件引用必须是列表')
        for reference in references:
            identifier(reference)
    return data


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.states = self.root / 'states'
        self.assets = self.root / 'assets'
        self.captures = self.root / 'captures'
        self.runs = self.root / 'runs'
        for path in [self.states, self.assets, self.captures, self.runs]:
            path.mkdir(parents=True, exist_ok=True)

    def save(self, data):
        data = validate_state(data)
        path = self.states / (data['id'] + '.json')
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)
        return data

    def load_all(self):
        return [validate_state(json.loads(path.read_text(encoding='utf-8'))) for path in sorted(self.states.glob('*.json'))]
