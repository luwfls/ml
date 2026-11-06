"""Group UI checks and loop/UX investigation; no Android hardware required."""
import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from automation.runner import run_loop
from automation.state import Store
from automation.vision import Recognizer
from automation.web import create_server

spec = importlib.util.spec_from_file_location('internet_sample', ROOT / 'examples/the-internet/run.py')
sample = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sample)


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium')
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    out = args.artifacts.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases, observations, network, technical = [], [], [], []

    def passed(case_id, expected, actual):
        cases.append({'case_id': case_id, 'status': 'passed', 'expected': expected,
                      'actual': actual, 'finished_at': datetime.now().astimezone().isoformat()})
        print(case_id, 'passed', flush=True)

    with tempfile.TemporaryDirectory() as directory, sync_playwright() as playwright:
        store = Store(Path(directory))
        for folder in ['states', 'assets', 'captures']:
            shutil.copytree(sample.SAMPLE / folder, store.root / folder, dirs_exist_ok=True)
        for state in store.load_all():
            state['group'] = ('复选框循环' if state['id'].startswith('checkbox') else
                              '独立终态' if state['id'] == 'element-cleared' else '元素循环')
            store.save(state)
        original_ids = {s['id'] for s in store.load_all()}
        server = create_server(store, port=0, adb=None)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        browser = None
        try:
            browser = playwright.chromium.launch(headless=True, **({'executable_path': args.chromium} if args.chromium else {}))
            page = browser.new_page(viewport={'width': 1600, 'height': 1100})
            page.on('pageerror', lambda error: technical.append({'type': 'pageerror', 'message': str(error)}))
            page.on('console', lambda message: technical.append({'type': 'console', 'level': message.type, 'message': message.text}) if message.type == 'error' else None)
            page.on('requestfailed', lambda request: technical.append({'type': 'requestfailed', 'url': request.url, 'message': request.failure}))

            def response_record(response):
                if '/api/' in response.url:
                    item = {'url': response.url, 'status': response.status, 'method': response.request.method,
                            'request': response.request.post_data}
                    try:
                        item['response'] = response.json()
                    except Exception as error:
                        item['body_unavailable'] = str(error)
                    network.append(item)

            page.on('response', response_record)
            base = f'http://127.0.0.1:{server.server_port}'

            def api(path):
                response = page.request.get(base + path)
                assert response.ok, response.text()
                return response.json()

            def group(name):
                return page.locator('.group-bar').get_by_role('button', name=re.compile('^' + re.escape(name) + r' \d+$'))

            def prompt(value):
                box = page.locator('.el-message-box:visible')
                box.locator('input').fill(value)
                box.get_by_role('button', name='确定', exact=True).click()
                expect(box).not_to_be_visible()

            page.goto(base)
            expect(page.locator('.state-card')).to_have_count(8)
            page.get_by_role('button', name='新建分组', exact=True).click()
            prompt('空组')
            expect(group('空组')).to_have_text('空组 0')
            page.reload()
            expect(group('空组')).to_be_visible()
            passed('GROUP-UI-01', '新建空分组刷新后保留', api('/api/groups'))

            group('复选框循环').click()
            expect(page.locator('.state-card')).to_have_count(4)
            page.locator('.state-card').filter(has_text='复选框 01').click()
            expect(page.locator('canvas')).to_be_visible()
            with page.expect_response(lambda r: r.url.endswith('/api/preview-group')) as preview:
                page.keyboard.press('F6')
            expect(page.locator('.preview-results .result-row')).to_have_count(4)
            matches = preview.value.json()['matches']
            assert {m['state_id'] for m in matches} == {f'checkbox-{v}' for v in ['00', '01', '10', '11']}
            assert [m['state_id'] for m in matches if m['eligible']] == ['checkbox-01']
            assert api('/api/runs') == []
            passed('GROUP-UI-02', '分组预览全部四个成员，仅01命中，不执行动作或生成运行', matches)
            page.get_by_placeholder('筛选名称 / ID / 文案').fill('01')
            with page.expect_response(lambda r: r.url.endswith('/api/preview-group')):
                page.get_by_role('button', name='当前分组预览 F6', exact=True).click()
            expect(page.locator('.preview-results .result-row')).to_have_count(1)
            page.screenshot(path=str(out / 'group-filter-preview.png'), full_page=True)
            observations.append({'id': 'UX-02', 'finding': '当前分组预览实际只预览搜索后可见成员，搜索01时4项变1项',
                                 'evidence': 'group-filter-preview.png', 'classification': 'scope-label ambiguity'})
            page.get_by_placeholder('筛选名称 / ID / 文案').fill('')

            pending = []
            page.route('**/api/preview-group', lambda route: pending.append(route))
            page.get_by_role('button', name='当前分组预览 F6', exact=True).click()
            expect(page.locator('.state-card')).to_have_count(4)
            group('元素循环').click()
            expect(page.locator('.state-card')).to_have_count(3)
            assert len(pending) == 1
            with page.expect_response(lambda r: r.url.endswith('/api/preview-group')):
                pending[0].continue_()
            expect(page.locator('.preview-results .result-row')).to_have_count(4)
            page.unroute('**/api/preview-group')
            page.screenshot(path=str(out / 'group-late-preview.png'), full_page=True)
            observations.append({'id': 'UX-05', 'finding': '延迟复选框组预览时切换元素组，返回的4个旧组结果仍显示在3成员新组下',
                                 'classification': 'stale asynchronous preview context', 'evidence': 'group-late-preview.png'})

            page.get_by_role('button', name='复制分组', exact=True).click()
            prompt('元素副本')
            expect(group('元素副本')).to_have_text('元素副本 3')
            copied = [s for s in api('/api/states') if s['group'] == '元素副本']
            copied_ids = {s['id'] for s in copied}
            assert len(copied) == 3 and not copied_ids.intersection(original_ids)
            assert len({s['recognition']['asset'] for s in copied}) == 3
            assert all(ref in copied_ids for s in copied for ref in s['conditions']['excluded_states'])
            passed('GROUP-UI-03', '复制分组生成独立State/模板并重映射组内排除条件', copied)
            group('元素副本').click()

            page.get_by_role('button', name='重命名', exact=True).click()
            prompt('元素副本改名')
            expect(group('元素副本改名')).to_have_text('元素副本改名 3')
            page.get_by_role('button', name='删除空分组', exact=True).click()
            page.locator('.el-message-box:visible').get_by_role('button', name='确定', exact=True).click()
            expect(page.locator('.el-alert')).to_contain_text('请先移动或删除分组中的 State')
            assert len([s for s in api('/api/states') if s['group'] == '元素副本改名']) == 3
            group('空组').click()
            page.get_by_role('button', name='删除空分组', exact=True).click()
            page.locator('.el-message-box:visible').get_by_role('button', name='确定', exact=True).click()
            expect(group('空组')).to_have_count(0)
            passed('GROUP-UI-04', '重命名保留成员，非空删除拒绝且无副作用，空组可删除', 'all assertions passed')

            page.get_by_role('button', name='循环流程', exact=True).click()
            panel = page.locator('.flow-layout')
            panel.locator('.el-form-item').filter(has=page.locator('.el-form-item__label').filter(has_text=re.compile('^名称$'))).locator('input').fill('分组快照测试')
            select = panel.locator('.el-form-item').filter(has=page.locator('.el-form-item__label').filter(has_text='按分组添加')).locator('.el-select')
            select.click()
            page.locator('.el-select-dropdown:visible').get_by_text('复选框循环', exact=True).click()
            panel.get_by_role('button', name='添加当前分组', exact=True).click()
            panel.get_by_role('button', name='添加当前分组', exact=True).click()
            expect(panel.locator('.reference-card')).to_have_count(4)
            panel.get_by_role('button', name='保存流程', exact=True).click()
            expect(page.get_by_text('流程已保存', exact=True)).to_be_visible()
            response = page.request.post(base + '/api/states/copy', data={'id': 'checkbox-01', 'name': '后加成员', 'group': '复选框循环'})
            assert response.ok, response.text()
            page.reload()
            expect(group('复选框循环')).to_have_text('复选框循环 5')
            flows = api('/api/flows')
            assert len(flows) == 1 and len(flows[0]['state_ids']) == 4
            passed('GROUP-UI-05', '按组添加去重，保存为成员快照，后来入组不静默改变已保存集合', flows)
            observations.append({'id': 'UX-03', 'finding': '按组添加是静态State集合拷贝，分组后来变5项，已保存集合仍4项', 'classification': 'intentional snapshot semantics; needs visible scope summary'})
            page.screenshot(path=str(out / 'groups-no-loop-entry.png'), full_page=True)
            assert page.get_by_role('button', name=re.compile('分组循环|运行分组')).count() == 0
            observations.append({'id': 'UX-01', 'finding': '分组页无独立循环或步进入口，仅F6单次预览；独立分组模式页面验收缺失', 'classification': 'missing product entry', 'evidence': 'groups-no-loop-entry.png'})

            # Exercise the native loop using group membership, without any saved flow.
            target = browser.new_page(viewport=sample.VIEWPORT, device_scale_factor=1, color_scheme='light', locale='en-US')
            with sample.serve_site() as site:
                sample.BASE = site
                members = [s['id'] for s in store.load_all() if s['group'] == '元素循环']
                assert set(members) == {'element-empty', 'element-added', 'element-delete'}

                def run(case_id, *, dry_run=False, cancel_after_success=False):
                    sample.navigate(target, '/add_remove_elements/')
                    directory = out / case_id
                    directory.mkdir()
                    device = sample.BrowserDevice(target, directory)
                    events, cancel = [], threading.Event()
                    def emit(event):
                        events.append(event)
                        if cancel_after_success and event['type'] == 'success':
                            cancel.set()
                    draft = {'state_ids': members, 'completion_count': 2, 'max_rounds': 8,
                             'timeout_seconds': 15, 'poll_ms': 50, 'dry_run': dry_run}
                    result = run_loop(store.load_all(), draft, device, Recognizer(store), cancel=cancel, emit=emit)
                    actual = {'result': result, 'clicks': device.clicks,
                              'delete_count': target.get_by_role('button', name='Delete', exact=True).count()}
                    write(directory / 'events.json', events)
                    write(directory / 'result.json', actual)
                    target.screenshot(path=str(directory / 'final.png'))
                    return actual, events

                actual, events = run('GROUP-RUN-01')
                assert actual['result']['status'] == 'passed' and actual['result']['success_count'] == 2
                assert actual['delete_count'] == 1 and len(actual['clicks']) == 3
                assert [e['state_id'] for e in events if e['type'] == 'action' and e['action']['type'] == 'click_match'] == ['element-empty', 'element-delete', 'element-empty']
                passed('GROUP-RUN-01', '按组成员循环：添加→删除→再添加，成功离开再进入累计2次，3次真实点击', actual)
                actual, _ = run('GROUP-RUN-02', dry_run=True)
                assert actual['result']['status'] == 'failed' and actual['result']['reason'] == 'max_rounds'
                assert actual['result']['success_count'] == 0 and not actual['clicks'] and actual['delete_count'] == 0
                passed('GROUP-RUN-02', '只识别不发输入，不虚构页面推进或循环成功，达到轮数上限退出', actual)
                actual, _ = run('GROUP-RUN-03', cancel_after_success=True)
                assert actual['result']['status'] == 'cancelled' and len(actual['clicks']) == 1
                passed('GROUP-RUN-03', '首次成功后取消，停止后续点击并返回cancelled', actual)
                for ids in [[], ['element-empty']]:
                    try:
                        run_loop(store.load_all(), {'state_ids': ids}, None, None)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('Empty/no-success group must be rejected before device access')
                passed('GROUP-RUN-04', '空组/无成功State在截图或输入前拒绝', 'ValueError before device access')
                sample.navigate(target, '/add_remove_elements/')
                directory = out / 'mixed-terminals'
                directory.mkdir()
                device = sample.BrowserDevice(target, directory)
                mixed = [s for s in store.load_all() if s['id'] in original_ids]
                result = run_loop(mixed, {'state_ids': list(original_ids), 'completion_count': 1}, device, Recognizer(store))
                assert result['status'] == 'passed' and not device.clicks
                observations.append({'id': 'UX-04', 'finding': '混入不同场景的成功State时，元素空页直接命中element-cleared成功，0次输入即结束', 'classification': 'terminal-state modeling risk; not an engine failure', 'result': result})
            assert not [e for e in technical if e['type'] in {'pageerror', 'requestfailed'}], technical
        finally:
            if sys.exc_info()[0] is not None and browser:
                write(out / 'failure.json', {'error': str(sys.exc_info()[1])})
                page.screenshot(path=str(out / 'failure.png'), full_page=True)
            write(out / 'cases.json', cases)
            write(out / 'observations.json', observations)
            write(out / 'network.json', network)
            write(out / 'technical.json', technical)
            if browser:
                browser.close()
            server.stop_runs()
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    main()
