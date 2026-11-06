"""Record and replay real screenshot States against The Internet demo site."""
import argparse
from contextlib import contextmanager
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import sys
import threading

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from automation.runner import run_loop
from automation.state import Store
from automation.vision import Recognizer

SAMPLE = Path(__file__).resolve().parent
BASE = None
VIEWPORT = {'width': 1280, 'height': 800}


@contextmanager
def serve_site():
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(SAMPLE / 'site')))
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def navigate(page, route):
    response = page.goto(BASE + route, wait_until='networkidle')
    assert response and response.status == 200, 'Demo page did not return HTTP 200'
    page.evaluate('document.fonts.ready')
    page.mouse.move(1100, 700)


def bounds(locator):
    box = locator.bounding_box()
    assert box, 'Expected a visible control'
    return [math.floor(box['x']), math.floor(box['y']),
            math.ceil(box['x'] + box['width']), math.ceil(box['y'] + box['height'])]


def click(page, box):
    page.mouse.click((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    page.mouse.move(1100, 700)


def screenshot(page):
    raw = page.screenshot(animations='disabled', caret='hide')
    return raw, cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def record(page, store):
    def state(state_id, name, box, *, target=None, role='normal', excluded=()):
        raw, frame = screenshot(page)
        (store.captures / (state_id + '.png')).write_bytes(raw)
        left, top, right, bottom = box
        assert cv2.imwrite(str(store.assets / (state_id + '.png')), frame[top:bottom, left:right])
        region = [left / 1280, top / 800, right / 1280, bottom / 800]
        actions = []
        if target:
            relative = [(target[0] - left) / (right - left), (target[1] - top) / (bottom - top),
                        (target[2] - left) / (right - left), (target[3] - top) / (bottom - top)]
            actions = [{'type': 'click_match', 'target_box': relative}, {'type': 'wait', 'ms': 100}]
        return store.save({
            'id': state_id, 'name': name, 'group': 'The Internet 公开系统样例', 'role': role,
            'recognition': {'type': 'image', 'asset': state_id + '.png', 'threshold': .999,
                            'scales': [1.0], 'region': region},
            'workbench': {'capture_id': state_id, 'roi_enabled': True, 'recognition_region': region},
            'actions': actions, 'conditions': {'required_states': [], 'excluded_states': list(excluded)},
        })

    navigate(page, '/checkboxes')
    inputs = page.locator('#checkboxes input')
    assert [inputs.nth(i).is_checked() for i in range(2)] == [False, True]
    first, second = bounds(inputs.nth(0)), bounds(inputs.nth(1))
    box = [first[0] - 2, first[1] - 2, first[2] + 105, second[3] + 2]
    state('checkbox-01', '复选框 01 → 点击第一项', box, target=first)
    click(page, first)
    state('checkbox-11', '复选框 11 → 点击第二项', box, target=second)
    click(page, second)
    state('checkbox-10', '复选框 10 → 点击第一项', box, target=first)
    click(page, first)
    state('checkbox-00', '复选框 00：全部取消成功', box, role='success')

    navigate(page, '/add_remove_elements/')
    add = bounds(page.get_by_role('button', name='Add Element', exact=True))
    state('element-empty', '没有元素 → 点击添加', add, target=add, excluded=['element-added'])
    click(page, add)
    delete = bounds(page.get_by_role('button', name='Delete', exact=True))
    state('element-added', '出现 Delete：添加成功', delete, role='success')
    state('element-delete', '存在元素 → 点击删除', delete, target=delete)
    click(page, delete)
    state('element-cleared', 'Delete 消失：删除成功', add, role='success', excluded=['element-added'])

    for flow_id, name, ids in [
        ('checkbox-cycle', '复选框三步切换至全部取消', ['checkbox-01', 'checkbox-11', 'checkbox-10', 'checkbox-00']),
        ('add-element', '添加一个页面元素', ['element-empty', 'element-added']),
        ('remove-element', '删除刚添加的页面元素', ['element-delete', 'element-cleared']),
    ]:
        store.save_flow({'id': flow_id, 'name': name, 'state_ids': ids,
                         'max_rounds': 12, 'timeout_seconds': 15, 'poll_ms': 100,
                         'completion_count': 1, 'dry_run': False})
    write_json(SAMPLE / 'manifest.json', {
        'system': 'The Internet', 'source': 'https://github.com/saucelabs/the-internet',
        'routes': ['/checkboxes/', '/add_remove_elements/'], 'viewport': VIEWPORT, 'device_scale_factor': 1,
        'deployment': 'Local static rendering of pinned upstream views; see site/provenance.json',
        'recorded_at': datetime.now().astimezone().isoformat(), 'browser': page.context.browser.version,
        'flow_order': ['checkbox-cycle', 'add-element', 'remove-element'],
        'device': 'Playwright screenshot/click adapter, not Android ADB',
    })


class BrowserDevice:
    def __init__(self, page, output):
        self.page, self.output, self.frames, self.clicks = page, output, 0, []

    def capture(self):
        raw, frame = screenshot(self.page)
        self.frames += 1
        (self.output / f'frame-{self.frames:02}.png').write_bytes(raw)
        return frame

    def execute(self, action, match, frame):
        assert action['type'] == 'click_match'
        assert match['found'] and not match['ambiguous']
        left, top, right, bottom = match['bbox']
        a, b, c, d = action.get('target_box', [0, 0, 1, 1])
        x, y = left + (a + c) / 2 * (right - left), top + (b + d) / 2 * (bottom - top)
        assert 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]
        self.clicks.append({'x': x, 'y': y, 'bbox': match['bbox']})
        self.page.mouse.click(x, y)
        self.page.mouse.move(1100, 700)


def verify(page, store, output):
    states = store.load_all()
    flows = {f['id']: f for f in store.list_flows()}
    cases = []
    for flow_id, expected_actions in [
        ('checkbox-cycle', ['checkbox-01', 'checkbox-11', 'checkbox-10']),
        ('add-element', ['element-empty']), ('remove-element', ['element-delete']),
    ]:
        directory = output / flow_id
        directory.mkdir(parents=True, exist_ok=True)
        if flow_id == 'checkbox-cycle':
            navigate(page, '/checkboxes')
            inputs = page.locator('#checkboxes input')
            assert [inputs.nth(i).is_checked() for i in range(2)] == [False, True]
        elif flow_id == 'add-element':
            navigate(page, '/add_remove_elements/')
            assert page.get_by_role('button', name='Delete', exact=True).count() == 0
        else:
            assert page.get_by_role('button', name='Delete', exact=True).count() == 1
        events = []
        device = BrowserDevice(page, directory)
        result = run_loop(states, flows[flow_id], device, Recognizer(store), emit=events.append)
        write_json(directory / 'events.json', events)
        write_json(directory / 'result.json', result)
        write_json(directory / 'clicks.json', device.clicks)
        assert result['status'] == 'passed', (flow_id, result)
        actions = [event['state_id'] for event in events if event['type'] == 'action' and event['action']['type'] == 'click_match']
        assert actions == expected_actions, actions
        if flow_id == 'checkbox-cycle':
            actual = [inputs.nth(i).is_checked() for i in range(2)]
            assert actual == [False, False], actual
        else:
            actual = page.get_by_role('button', name='Delete', exact=True).count()
            assert actual == (1 if flow_id == 'add-element' else 0), actual
        page.screenshot(path=str(directory / 'final.png'))
        cases.append({'flow_id': flow_id, 'status': 'passed', 'actions': actions,
                      'independent_dom_result': actual, 'result': result})
        print(flow_id, 'passed:', actions, flush=True)
    write_json(output / 'cases.json', cases)


def main():
    global BASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true', help='Explicitly regenerate the checked-in States and templates')
    parser.add_argument('--chromium', help='Optional installed Chromium executable')
    parser.add_argument('--artifacts', type=Path, default=SAMPLE / 'evidence')
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    technical, network = [], []
    with serve_site() as base, sync_playwright() as playwright:
        BASE = base
        browser = playwright.chromium.launch(headless=True, **({'executable_path': args.chromium} if args.chromium else {}))
        try:
            page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1, color_scheme='light', locale='en-US')
            page.on('pageerror', lambda error: technical.append({'type': 'pageerror', 'message': str(error)}))
            page.on('console', lambda message: technical.append({'type': 'console', 'level': message.type, 'message': message.text}) if message.type == 'error' else None)
            page.on('requestfailed', lambda request: technical.append({'type': 'requestfailed', 'url': request.url, 'message': request.failure}))
            page.on('response', lambda response: network.append({'url': response.url, 'status': response.status, 'method': response.request.method}))
            store = Store(SAMPLE)
            if args.record:
                record(page, store)
            verify(page, store, args.artifacts)
            assert not technical, technical
            assert not [r for r in network if r['status'] >= 400], network
        finally:
            write_json(args.artifacts / 'technical.json', technical)
            write_json(args.artifacts / 'network.json', network)
            browser.close()


if __name__ == '__main__':
    main()
