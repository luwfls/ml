import copy
import json
import math
import re
import shutil
from uuid import uuid4
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
    data.setdefault('group', '')
    if not isinstance(data['group'], str) or len(data['group']) > 200:
        raise ValueError('分组名必须为字符串，最多 200 字')
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
        if action['type'] == 'click_match' and 'target_box' in action:
            box = action['target_box']
            if not isinstance(box, list) or len(box) != 4:
                raise ValueError('点击区需要四个相对坐标')
            for value in box:
                number(value, -100, 100)
            if box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError('点击区不能为空')
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
        self.flows = self.root / 'flows'
        for path in [self.states, self.assets, self.captures, self.runs, self.flows]:
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

    def write_json(self, path, value):
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)

    def list_groups(self):
        file = self.root / 'groups.json'
        names = set(json.loads(file.read_text(encoding='utf-8')) if file.exists() else [])
        names.update(s['group'] for s in self.load_all() if s['group'])
        return [{'name': name} for name in sorted(names)]

    def update_group(self, action, name, new_name=None):
        states = {path: path.read_bytes() for path in self.states.glob('*.json')}
        assets = set(self.assets.glob('*.png'))
        groups_file = self.root / 'groups.json'
        groups = groups_file.read_bytes() if groups_file.exists() else None
        try:
            return self._update_group(action, name, new_name)
        except Exception:
            for path in self.states.glob('*.json'):
                if path not in states: path.unlink()
            for path, raw in states.items():
                if not path.exists() or path.read_bytes() != raw:
                    temporary = path.with_suffix('.rollback')
                    temporary.write_bytes(raw)
                    temporary.replace(path)
            for path in self.assets.glob('*.png'):
                if path not in assets: path.unlink()
            if groups is None: groups_file.unlink(missing_ok=True)
            else: groups_file.write_bytes(groups)
            raise

    def _update_group(self, action, name, new_name=None):
        groups = {g['name'] for g in self.list_groups()}
        if action not in {'create', 'rename', 'copy', 'delete'}:
            raise ValueError('无效分组操作')
        target = name if action == 'create' else new_name
        if action != 'delete' and (not isinstance(target, str) or not target.strip() or len(target) > 200):
            raise ValueError('分组名不能为空且最多 200 字')
        if action != 'create' and name not in groups:
            raise ValueError('分组不存在')
        if action != 'delete' and target in groups:
            raise ValueError('分组已存在')
        members = [s for s in self.load_all() if s['group'] == name]
        if action == 'delete' and members:
            raise ValueError('请先移动或删除分组中的 State')
        if action == 'rename':
            updated = []
            try:
                for state in members:
                    self.save({**state, 'group': target})
                    updated.append(state)
            except Exception:
                for state in updated: self.save(state)
                raise
        elif action == 'copy':
            ids = {s['id']: uuid4().hex for s in members}
            staged = []
            created_assets = []
            try:
                for state in members:
                    copied = copy.deepcopy(state)
                    copied.update(id=ids[state['id']], group=target)
                    for key in ['required_states', 'excluded_states']:
                        copied['conditions'][key] = [ids.get(ref, ref) for ref in copied['conditions'][key]]
                    if copied['recognition']['type'] == 'image':
                        asset = uuid4().hex + '.png'
                        created_assets.append(self.assets / asset)
                        shutil.copyfile(self.assets / copied['recognition']['asset'], self.assets / asset)
                        copied['recognition']['asset'] = asset
                    staged.append(copied)
                for copied in staged: self.save(copied)
            except Exception:
                for copied in staged:
                    (self.states / (copied['id'] + '.json')).unlink(missing_ok=True)
                    (self.states / (copied['id'] + '.tmp')).unlink(missing_ok=True)
                for asset in created_assets: asset.unlink(missing_ok=True)
                raise
        if action in {'rename', 'delete'}:
            groups.remove(name)
        if action != 'delete':
            groups.add(target)
        self.write_json(self.root / 'groups.json', sorted(groups))
        return {'ok': True}

    def copy_state(self, source, new_id, name=None, group=None):
        source, new_id = identifier(source), identifier(new_id)
        if (self.states / (new_id + '.json')).exists():
            raise ValueError('State ID 已存在')
        state = next((s for s in self.load_all() if s['id'] == source), None)
        if state is None:
            raise ValueError('State 不存在')
        state['id'] = new_id
        if name is not None: state['name'] = name
        if group is not None: state['group'] = group
        if state['recognition']['type'] == 'image':
            asset = uuid4().hex + '.png'
            shutil.copyfile(self.assets / state['recognition']['asset'], self.assets / asset)
            state['recognition']['asset'] = asset
        try:
            return self.save(state)
        except Exception:
            if state['recognition']['type'] == 'image':
                (self.assets / state['recognition']['asset']).unlink(missing_ok=True)
            (self.states / (new_id + '.tmp')).unlink(missing_ok=True)
            raise

    def delete_state(self, state_id):
        state_id = identifier(state_id)
        for state in self.load_all():
            if state['id'] != state_id and state_id in state['conditions']['required_states'] + state['conditions']['excluded_states']:
                raise ValueError('State 被条件引用，不能删除')
        flows = self.list_flows()
        legacy = self.root / 'flow.json'
        if legacy.exists() and not (self.root / 'flows-migrated.json').exists():
            flows.append(json.loads(legacy.read_text(encoding='utf-8')))
        if any(state_id in f['state_ids'] for f in flows):
            raise ValueError('State 被流程引用，不能删除')
        (self.states / (state_id + '.json')).unlink()
        return {'ok': True}

    def list_flows(self):
        legacy = self.root / 'flow.json'
        marker = self.root / 'flows-migrated.json'
        if not marker.exists():
            if legacy.exists() and not (self.flows / 'default.json').exists():
                self.save_flow({**json.loads(legacy.read_text(encoding='utf-8')), 'id': 'default', 'name': '默认流程'})
            self.write_json(marker, True)
        return [json.loads(path.read_text(encoding='utf-8')) for path in sorted(self.flows.glob('*.json'))]

    def save_flow(self, flow):
        from .runner import validate_flow
        flow = copy.deepcopy(flow)
        identifier(flow.get('id'))
        flow.setdefault('name', flow['id'])
        validate_flow(flow, self.load_all())
        self.write_json(self.flows / (flow['id'] + '.json'), flow)
        return flow

    def copy_flow(self, source, new_id, name=None):
        identifier(new_id)
        if (self.flows / (new_id + '.json')).exists():
            raise ValueError('流程 ID 已存在')
        flow = next((f for f in self.list_flows() if f['id'] == identifier(source)), None)
        if flow is None: raise ValueError('流程不存在')
        return self.save_flow({**flow, 'id': new_id, 'name': name or flow['name']})

    def delete_flow(self, flow_id):
        (self.flows / (identifier(flow_id) + '.json')).unlink()
        return {'ok': True}
