"""Real Chromium workbench smoke test with a foreground fake-device backend.

Run with a Python environment containing playwright and --python pointing at
the project's environment. Build the frontend first. No actual ADB is invoked.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect, Error as PlaywrightError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python', required=True)
    parser.add_argument('--chromium')
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.artifacts.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    with tempfile.TemporaryDirectory() as directory:
        data = Path(directory)
        with (data / 'backend.log').open('w') as log:
            process = subprocess.Popen([args.python, str(root / 'tests/browser_backend.py'), '--data', str(data), '--port', str(port)], stdout=log, stderr=log, cwd=root)
            try:
                for _ in range(100):
                    try:
                        urllib.request.urlopen(base + '/api/health', timeout=.5).close()
                        break
                    except OSError:
                        if process.poll() is not None:
                            raise RuntimeError((data / 'backend.log').read_text())
                        time.sleep(.05)
                else:
                    raise RuntimeError('Browser fixture failed to become ready')
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, **({'executable_path': args.chromium} if args.chromium else {}))
                    try:
                        page = browser.new_page(viewport={'width': 1600, 'height': 1100})
                        errors = []
                        cases, network, technical = [], [], []
                        active_case, case_started = 'UI-01', datetime.now().astimezone().isoformat()
                        def begin(case_id):
                            nonlocal active_case, case_started
                            active_case, case_started = case_id, datetime.now().astimezone().isoformat()
                        def record(case_id, expected, actual):
                            screenshot = case_id + '.png'
                            page.screenshot(path=str(args.artifacts / screenshot), full_page=True)
                            cases.append({'case_id':case_id,'status':'通过','started_at':case_started,
                                          'finished_at':datetime.now().astimezone().isoformat(),'url':page.url,
                                          'expected':expected,'actual':actual,'screenshot':screenshot})
                        def response_evidence(response):
                            if '/api/' in response.url or response.status >= 400:
                                item = {'case_id':active_case,'time':datetime.now().astimezone().isoformat(),
                                        'method':response.request.method,'url':response.url,
                                        'request':response.request.post_data,'status':response.status,'resource_type':response.request.resource_type}
                                try:
                                    item['response'] = response.json() if '/api/' in response.url else response.text()
                                except (PlaywrightError, ValueError) as error:
                                    item['response'] = None
                                    item['body_unavailable'] = str(error)
                                network.append(item)
                        page.on('response', response_evidence)
                        page.on('console', lambda message: technical.append({'case_id':active_case,'type':'console','level':message.type,'message':message.text,'location':message.location}))
                        page.on('requestfailed', lambda request: technical.append({'case_id':active_case,'type':'requestfailed','url':request.url,'error':request.failure}))
                        state_posts = []
                        page.on('request', lambda request: state_posts.append(request.url) if request.method == 'POST' and request.url.endswith('/api/states') else None)
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        def api(path):
                            response = page.request.get(base + path)
                            assert response.ok, response.text()
                            return response.json()
                        def wait_status(run_id, status):
                            for _ in range(150):
                                if api('/api/runs/' + run_id)['status'] == status:
                                    return
                                page.wait_for_timeout(50)
                            raise AssertionError(f'Run did not reach {status}')
                        def prompt(value):
                            box = page.locator('.el-message-box:visible')
                            box.locator('input').fill(value)
                            box.get_by_role('button', name='确定', exact=True).click()
                            expect(box).not_to_be_visible()
                        def field(scope, label):
                            return scope.locator('.el-form-item').filter(has=page.locator('.el-form-item__label').filter(has_text=re.compile('^' + re.escape(label) + '$')))

                        page.goto(base)
                        expect(page.get_by_text('API 在线', exact=True)).to_be_visible()
                        page.get_by_role('button', name='新建分组', exact=True).click()
                        prompt('收货验证')
                        expect(page.locator('.group-bar').get_by_role('button', name='收货验证 0', exact=True)).to_be_visible()
                        page.locator('input[type=file]').set_input_files(data / 'browser-page.png')
                        canvas = page.locator('canvas')
                        expect(canvas).to_be_visible()
                        bounds = canvas.bounding_box()
                        page.mouse.move(bounds['x'] + 120, bounds['y'] + 100)
                        page.mouse.down()
                        page.mouse.move(bounds['x'] + 351, bounds['y'] + 211, steps=10)
                        page.mouse.up()
                        page.keyboard.press('F4')
                        expect(page.locator('.el-drawer:visible')).to_have_count(1)
                        assert api('/api/states') == []
                        drawer = page.locator('.state-editor:visible')
                        expect(drawer.get_by_role('checkbox', name='仅在识别区内搜索', exact=True)).to_be_checked()
                        expect(page.get_by_role('radio', name='搜索 ROI', exact=True)).to_have_count(0)
                        drawer.get_by_role('button', name='取消编辑', exact=True).click()
                        expect(page.locator('.el-drawer:visible')).to_have_count(0)
                        left, right = page.locator('.capture-pane').bounding_box(), drawer.bounding_box()
                        assert left['x'] + left['width'] <= right['x'], (left, right)
                        state_id = field(drawer, 'ID').locator('input').input_value()
                        assert re.fullmatch('[a-f0-9]{32}', state_id)
                        expect(field(drawer, 'ID').locator('input')).to_have_attribute('readonly', 'readonly')
                        page.keyboard.press('F4')
                        for invalid_name in ['', '   ']:
                            field(drawer, '名称').locator('input').fill(invalid_name)
                            page.keyboard.press('F4')
                            expect(drawer.locator('.el-alert--error')).to_contain_text('State 名称不能为空')
                            expect(field(drawer, '名称').locator('.el-form-item__error')).to_have_text('请输入 State 名称')
                            expect(field(drawer, '名称').locator('input')).to_be_focused()
                            assert state_posts == []
                        page.screenshot(path=str(args.artifacts / 'state-name-validation.png'), animations='disabled')
                        field(drawer, '名称').locator('input').fill('确认收货')
                        expect(drawer.locator('.el-alert--error')).to_have_count(0)
                        def reject_save(route):
                            route.fulfill(status=400, content_type='application/json', body=json.dumps({'error': '保存失败测试提示'}))
                        page.route('**/api/states', reject_save)
                        page.keyboard.press('F4')
                        expect(drawer.locator('.el-alert--error')).to_contain_text('保存失败测试提示')
                        expect(page.locator('.el-drawer:visible')).to_have_count(1)
                        page.unroute('**/api/states', reject_save)
                        field(drawer, '角色').locator('.el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text=re.compile('success|成功断言')).click()
                        field(drawer, '名称').locator('input').focus()
                        page.keyboard.press('F4')
                        expect(page.locator('.el-drawer:visible')).to_have_count(0)
                        expect(page.locator('.state-card').filter(has_text=state_id)).to_be_visible()
                        initial = api('/api/states')[0]
                        assert initial['workbench']['capture_id']
                        original_image = page.request.get(base + '/captures/' + initial['workbench']['capture_id'] + '.png')
                        assert original_image.ok and original_image.body() == (data / 'browser-page.png').read_bytes()
                        assert initial['group'] == '收货验证'
                        assert initial['workbench']['roi_enabled'] is True
                        assert initial['recognition']['region'] == initial['workbench']['recognition_region']
                        assert initial['recognition']['region'] != [0, 0, 1, 1]
                        record('UI-01', '空名无写入、有效名称自动保存模板及原图', '空名与服务端失败均显示在抽屉；补名后 F4 保存、自动 ID 与原图一致')
                        begin('UI-02')
                        drawer.get_by_role('button', name='识别预览', exact=True).click()
                        expect(page.locator('.preview-results')).to_contain_text('命中')
                        drawer.get_by_role('button', name='取消编辑', exact=True).click()
                        page.screenshot(path=str(args.artifacts / 'state-workbench.png'), full_page=True)
                        # Prompt has already been shown: hidden dialog must not disable F6.
                        canvas.click(position={'x': 10, 'y': 10})
                        with page.expect_response(lambda r: r.url.endswith('/api/preview-group')):
                            page.keyboard.press('F6')
                        assert not errors, errors

                        record('UI-02', '草稿和分组预览命中且不执行动作', '图片预览命中；F6 发送分组预览请求')
                        begin('UI-03')
                        # Live Vue form persists combined recognition and ROI, with no prototype storage.
                        page.locator('.state-card').click()
                        drawer.get_by_text('文字匹配', exact=True).click()
                        candidates = field(drawer, '候选文案')
                        candidates.locator('input').first.fill('CONFIRM')
                        candidates.get_by_role('button', name='添加候选文案', exact=True).click()
                        candidates.locator('input').nth(1).fill('完成')
                        candidates.get_by_role('button', name='添加候选文案', exact=True).click()
                        candidates.locator('input').nth(2).fill('移除项')
                        candidates.get_by_role('button', name='移除', exact=True).nth(2).click()
                        drawer.get_by_text('或 OR', exact=True).click()
                        page.keyboard.press('F4')
                        expect(page.locator('.el-drawer:visible')).to_have_count(1)
                        page.set_viewport_size({'width': 1600, 'height': 1600})
                        page.evaluate('window.scrollTo(0,0)')
                        page.screenshot(path=str(args.artifacts / 'state-save-drawer.png'), full_page=False, animations='disabled')
                        page.set_viewport_size({'width': 1600, 'height': 1100})
                        drawer.get_by_role('button', name='取消编辑', exact=True).click()
                        with page.expect_response(lambda r: r.url.endswith('/api/states') and r.request.method == 'POST') as save_response:
                            drawer.get_by_role('button', name='保存 State', exact=True).click()
                        assert save_response.value.ok, save_response.value.text()
                        expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_enabled()
                        expect(page.get_by_text('State 已保存', exact=True).first).to_be_visible()
                        combined = api('/api/states')[0]['recognition']
                        assert combined['type'] == 'combined' and combined['operator'] == 'or'
                        assert combined['text']['texts'] == ['CONFIRM', '完成']
                        assert combined['image']['region'] == combined['text']['region']
                        expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_enabled()
                        expect(page.locator('.el-message')).to_have_count(0)
                        page.screenshot(path=str(args.artifacts / 'state-workbench-A-combined.png'), full_page=True)
                        page.reload()
                        expect(page.get_by_text('API 在线', exact=True)).to_be_visible()
                        page.locator('.state-card').click()
                        expect(canvas).to_be_visible()
                        expect(page.locator('.capture-workbench')).to_contain_text('截图 640 × 480 px')
                        expect(page.locator('.capture-workbench')).to_contain_text('120, 100, 351, 211')
                        page.screenshot(path=str(args.artifacts / 'state-original-restored.png'), full_page=True)
                        expect(drawer.get_by_role('checkbox', name='文字匹配', exact=True)).to_be_checked()
                        expect(drawer.locator('input[type=radio][value=or]')).to_be_checked()
                        assert field(drawer, '候选文案').locator('input').evaluate_all('(nodes)=>nodes.map(node=>node.value)') == ['CONFIRM', '完成']
                        record('UI-03', '保存后刷新保持候选、组合关系、原图和框选', '两候选文案及 OR 恢复，完整截图 640×480 与识别区恢复')
                        begin('UI-04')
                        expect(drawer.get_by_role('button', name='识别预览', exact=True)).to_be_enabled()
                        drawer.get_by_role('button', name='识别预览', exact=True).click()
                        expect(drawer.locator('.el-alert--error')).to_contain_text('当前未启用 OCR')
                        with page.expect_response(lambda r: r.url.endswith('/api/preview')) as image_preview:
                            drawer.get_by_role('button', name='仅图片预览', exact=True).click()
                        assert image_preview.value.ok, image_preview.value.text()
                        expect(page.locator('.preview-results')).to_contain_text('仅图片预览（未判断文字及图文关系）')
                        expect(page.locator('.preview-results')).to_contain_text('命中')
                        page.screenshot(path=str(args.artifacts / 'preview-image-only.png'), full_page=True)
                        expect(drawer.get_by_role('button', name='执行动作 F5', exact=True)).to_be_enabled()
                        drawer.get_by_role('button', name='执行动作 F5', exact=True).click()
                        expect(drawer.locator('.el-alert--error')).to_contain_text('选择在线 ADB 设备')
                        record('UI-04', '缺 OCR/设备要解释，允许仅图片预览', '完整预览显示 OCR 原因，仅图片命中且标注范围，执行提示先选设备')
                        begin('UI-05')
                        page.locator('input[type=file]').set_input_files(data / 'browser-page.png')
                        expect(canvas).to_be_visible()
                        # Text-only configuration is also supported, without losing candidate text.
                        drawer.get_by_text('图片匹配', exact=True).click()
                        with page.expect_response(lambda r: r.url.endswith('/api/states') and r.request.method == 'POST') as save_response:
                            drawer.get_by_role('button', name='保存 State', exact=True).click()
                        assert save_response.value.ok, save_response.value.text()
                        expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_enabled()
                        assert api('/api/states')[0]['recognition']['type'] == 'text'
                        drawer.get_by_text('图片匹配', exact=True).click()
                        drawer.get_by_text('且 AND', exact=True).click()
                        with page.expect_response(lambda r: r.url.endswith('/api/states') and r.request.method == 'POST') as save_response:
                            drawer.get_by_role('button', name='保存 State', exact=True).click()
                        assert save_response.value.ok, save_response.value.text()
                        expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_enabled()
                        assert api('/api/states')[0]['recognition']['operator'] == 'and'
                        page.locator('input[type=file]').set_input_files(data / 'browser-page.png')
                        expect(canvas).to_be_visible()
                        expect(page.locator('.capture-workbench')).to_contain_text('120, 100, 351, 211')
                        drawer.get_by_text('仅在识别区内搜索', exact=True).click()
                        with page.expect_response(lambda r: r.url.endswith('/api/states') and r.request.method == 'POST') as save_response:
                            drawer.get_by_role('button', name='保存 State', exact=True).click()
                        assert save_response.value.ok, save_response.value.text()
                        expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_enabled()
                        combined = api('/api/states')[0]['recognition']
                        assert combined['image']['region'] == combined['text']['region'] == [0, 0, 1, 1]
                        page.locator('.state-card').click()
                        expect(drawer.get_by_role('checkbox', name='仅在识别区内搜索', exact=True)).not_to_be_checked()
                        drawer.get_by_text('仅在识别区内搜索', exact=True).click()
                        drawer.get_by_text('文字匹配', exact=True).click()
                        with page.expect_response(lambda r: r.url.endswith('/api/states') and r.request.method == 'POST') as save_response:
                            drawer.get_by_role('button', name='保存 State', exact=True).click()
                        assert save_response.value.ok, save_response.value.text()
                        expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_enabled()
                        assert api('/api/states')[0]['recognition']['type'] == 'image'
                        # Saving a new selection replaces the saved template automatically.
                        previous_asset = api('/api/states')[0]['recognition']['asset']
                        canvas.scroll_into_view_if_needed()
                        bounds = canvas.bounding_box()
                        page.mouse.move(bounds['x'] + 110, bounds['y'] + 90)
                        page.mouse.down()
                        page.mouse.move(bounds['x'] + 360, bounds['y'] + 220, steps=10)
                        page.mouse.up()
                        with page.expect_response(lambda r: r.url.endswith('/api/states') and r.request.method == 'POST') as save_response:
                            drawer.get_by_role('button', name='保存 State', exact=True).click()
                        assert save_response.value.ok, save_response.value.text()
                        expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_enabled()
                        reframed = api('/api/states')[0]
                        assert reframed['recognition']['asset'] != previous_asset
                        assert reframed['recognition']['region'] == [110/640, 90/480, 360/640, 220/480]
                        expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_enabled()
                        expect(page.locator('.el-message')).to_have_count(0)
                        page.screenshot(path=str(args.artifacts / 'state-workbench-A.png'), full_page=True)
                        page.set_viewport_size({'width': 900, 'height': 1100})
                        left, right = page.locator('.capture-pane').bounding_box(), drawer.bounding_box()
                        assert left['y'] + left['height'] <= right['y']
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                        record('UI-05', '900px 下 State 编辑器上下排列且无横向溢出', '识别区与表单无交叠，页面宽度未超视口')
                        page.set_viewport_size({'width': 1600, 'height': 1100})
                        drawer.get_by_role('button', name='取消编辑', exact=True).click()

                        begin('UI-06')
                        # Cancelling a new crop must leave the persisted template intact.
                        original = api('/api/states')[0]
                        asset_before = page.request.get(base + '/assets/' + original['recognition']['asset']).body()
                        page.locator('.state-card').click()
                        canvas.scroll_into_view_if_needed()
                        bounds = canvas.bounding_box()
                        page.mouse.move(bounds['x'] + 410, bounds['y'] + 300)
                        page.mouse.down()
                        page.mouse.move(bounds['x'] + 571, bounds['y'] + 381, steps=10)
                        page.mouse.up()
                        drawer.get_by_role('button', name='裁剪识别区', exact=True).click()
                        expect(field(drawer, '图片资源').locator('input')).not_to_have_value(original['recognition']['asset'])
                        drawer.get_by_role('button', name='取消编辑', exact=True).click()
                        assert api('/api/states')[0]['recognition']['asset'] == original['recognition']['asset']
                        assert page.request.get(base + '/assets/' + original['recognition']['asset']).body() == asset_before

                        # Independently configured input uses a freshly cropped recognition anchor.
                        page.locator('.state-card').click()
                        drawer.get_by_role('button', name='复制 State', exact=True).click()
                        prompt('confirm-click')
                        field(drawer, '角色').locator('.el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text=re.compile('^normal$|^普通$')).click()
                        field(drawer, '输入动作').locator('.el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text='点击匹配位置').click()
                        canvas.scroll_into_view_if_needed()
                        bounds = canvas.bounding_box()
                        page.mouse.move(bounds['x'] + 120, bounds['y'] + 100)
                        page.mouse.down()
                        page.mouse.move(bounds['x'] + 351, bounds['y'] + 211, steps=10)
                        page.mouse.up()
                        page.keyboard.press('F3')
                        page.mouse.move(bounds['x'] + 410, bounds['y'] + 300)
                        page.mouse.down()
                        page.mouse.move(bounds['x'] + 571, bounds['y'] + 381, steps=10)
                        page.mouse.up()
                        drawer.get_by_role('button', name='裁剪并采用独立点击区', exact=True).click()
                        expect(field(drawer, '点击区域')).not_to_contain_text('匹配框中心')
                        drawer.get_by_role('button', name='保存 State', exact=True).click()
                        for _ in range(100):
                            copied = next(s for s in api('/api/states') if s['id'] == 'confirm-click')
                            if copied['actions']: break
                            page.wait_for_timeout(50)
                        assert copied['actions'][0]['type'] == 'click_match'
                        assert len(copied['actions'][0]['target_box']) == 4
                        page.locator('.toolbar .el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text=re.compile('^browser-device ·')).click()
                        drawer.get_by_role('button', name='执行动作 F5', exact=True).click()
                        page.locator('.el-message-box:visible').get_by_role('button', name='确定', exact=True).click()
                        for _ in range(100):
                            if (data / 'fake-actions.log').exists(): break
                            page.wait_for_timeout(50)
                        assert 'target_box' in (data / 'fake-actions.log').read_text()
                        drawer.get_by_role('button', name='删除 State', exact=True).click()
                        page.locator('.el-message-box:visible').get_by_role('button', name='确定', exact=True).click()
                        expect(page.locator('.state-card')).to_have_count(1)

                        record('UI-06', '取消裁剪不覆盖原模板，保存的独立点击区可执行', '原模板字节未改变，F5 确认后替身收到 target_box 动作')
                        begin('UI-07')
                        page.get_by_role('button', name='循环流程', exact=True).click()
                        form = page.locator('.flow-layout .el-card').nth(1)
                        expect(field(form, '流程 ID')).to_have_count(0)
                        expect(form.get_by_text('配置 JSON 预览', exact=True)).to_have_count(0)
                        field(form, '名称').locator('input').fill('收货循环')
                        field(form, '完成次数').locator('input').fill('2')
                        field(form, '轮间等待 ms').locator('input').fill('100')
                        field(form, '超时（秒）').locator('input').fill('30')
                        with page.expect_response(lambda r: r.url.endswith('/api/flows') and r.request.method == 'POST') as empty_flow_response:
                            form.get_by_role('button', name='保存流程', exact=True).click()
                        assert empty_flow_response.value.ok, empty_flow_response.value.text()
                        empty_flow = empty_flow_response.value.json()
                        receive_flow_id = empty_flow['id']
                        assert receive_flow_id and empty_flow['state_ids'] == []
                        expect(page.locator('.flow-card').filter(has_text='收货循环')).to_be_visible()
                        expect(form.get_by_role('button', name='保存并启动', exact=True)).to_be_disabled()
                        expect(form.get_by_role('button', name='复制', exact=True)).to_be_enabled()
                        expect(page.locator('.flow-layout')).not_to_contain_text(receive_flow_id)
                        expect(page.locator('.el-message')).to_have_count(0)
                        page.screenshot(path=str(args.artifacts / 'flow-optional-states.png'), full_page=True)
                        page.set_viewport_size({'width':900,'height':1100})
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'flow layout overflow'
                        page.screenshot(path=str(args.artifacts / 'flow-900.png'), full_page=True)
                        page.set_viewport_size({'width':1600,'height':1100})
                        field(form, '按分组添加').locator('.el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text='收货验证').click()
                        form.get_by_role('button', name='添加当前分组', exact=True).click()
                        form.get_by_role('button', name='保存流程', exact=True).click()
                        expect(page.locator('.flow-card').filter(has_text='收货循环')).to_be_visible()
                        expect(page.locator('.flow-layout')).not_to_contain_text(api('/api/states')[0]['id'])
                        form.get_by_role('button', name='复制', exact=True).click()
                        expect(page.locator('.el-message-box:visible')).to_contain_text('新流程名称')
                        prompt('收货循环副本')
                        expect(page.locator('.flow-card').filter(has_text='收货循环副本')).to_be_visible()
                        assert len(api('/api/flows')) == 2
                        assert len({f['id'] for f in api('/api/flows')}) == 2
                        record('UI-07', '流程 ID 隐藏、空选可保存、按名称复制', '空选保存成功且启动禁用；添加分组后保存，两个副本内部 ID 不同')
                        begin('UI-08')
                        page.locator('.flow-card').filter(has=page.get_by_text('收货循环', exact=True)).click()
                        form.get_by_role('button', name='保存并启动', exact=True).click()
                        for _ in range(100):
                            runs = api('/api/runs')
                            if runs: break
                            page.wait_for_timeout(50)
                        assert len(runs) == 1
                        run_id = runs[0]['id']
                        panel = page.locator('.el-card').filter(has=page.get_by_role('heading', name='运行记录与证据'))
                        expect(panel.get_by_role('button', name='暂停', exact=True)).to_be_enabled()
                        panel.get_by_role('button', name='暂停', exact=True).click()
                        wait_status(run_id, 'paused')
                        before = api('/api/runs/' + run_id)
                        page.wait_for_timeout(250)
                        after = api('/api/runs/' + run_id)
                        assert before['frame_url'] == after['frame_url']
                        expect(panel.get_by_role('button', name='继续', exact=True)).to_be_enabled()
                        panel.get_by_role('button', name='继续', exact=True).click()
                        wait_status(run_id, 'running')
                        panel.get_by_role('button', name='停止', exact=True).click()
                        wait_status(run_id, 'cancelled')
                        expect(panel.locator('.run-summary')).to_contain_text('cancelled')
                        expect(panel.locator('.evidence img')).to_be_visible()
                        page.screenshot(path=str(args.artifacts / 'loop-workbench.png'), full_page=True)
                        page.reload()
                        expect(page.get_by_text('API 在线', exact=True)).to_be_visible()
                        expect(page.locator('.state-card')).to_have_count(1)
                        page.get_by_role('button', name='循环流程', exact=True).click()
                        expect(page.locator('.flow-card')).to_have_count(2)
                        panel = page.locator('.el-card').filter(has=page.get_by_role('heading', name='运行记录与证据'))
                        panel.locator('.el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text=run_id).click()
                        expect(panel.locator('.run-summary')).to_contain_text('cancelled')
                        # Keep process-based tasks alive while browser screenshots/control run.
                        record('UI-08', '暂停确认后截图稳定，继续/停止及刷新历史有效', '暂停后 frame_url 不变，继续运行，停止后 cancelled，刷新可重开')
                        begin('UI-09')
                        saved_flow = next(f for f in api('/api/flows') if f['id'] == receive_flow_id)
                        assert page.request.post(base + '/api/flows', data={**saved_flow, 'completion_count': 100}).ok
                        page.get_by_role('button', name='任务', exact=True).click()
                        tasks = page.locator('.task-panel')
                        tasks.get_by_role('button', name='新建任务', exact=True).click()
                        field(tasks, '任务名称').locator('input').fill('多设备收货验证')
                        field(tasks, '关联流程').locator('.el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text=re.compile('^收货循环$')).click()
                        tasks.get_by_role('button', name='保存任务', exact=True).click()
                        expect(tasks.locator('.task-card')).to_have_count(1)
                        task = api('/api/tasks')[0]
                        assert task['id'] and task['flow_id'] == receive_flow_id
                        page.set_viewport_size({'width':900,'height':1100})
                        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'task layout overflow'
                        page.screenshot(path=str(args.artifacts / 'task-900.png'), full_page=True)
                        page.set_viewport_size({'width':1600,'height':1100})
                        tasks.get_by_role('button', name='手动启动', exact=True).click()
                        dialog = page.locator('.el-dialog:visible')
                        field(dialog, 'ADB 设备').locator('.el-select').click()
                        expect(page.locator('.el-select-dropdown__item:visible').filter(has_text='browser-offline')).to_have_class(re.compile('is-disabled'))
                        page.locator('.el-select-dropdown__item:visible').filter(has_text=re.compile('^browser-device ·')).click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text=re.compile('^browser-device-2 ·')).click()
                        dialog.locator('.el-dialog__header').click()
                        dialog.get_by_role('button', name='启动', exact=True).click()
                        page.locator('.el-message-box:visible').get_by_role('button', name='确定', exact=True).click()
                        for _ in range(100):
                            task_runs = [r for r in api('/api/runs') if r.get('task_id') == task['id']]
                            if len(task_runs) == 2: break
                            page.wait_for_timeout(50)
                        assert len(task_runs) == 2, task_runs
                        assert {r['serial'] for r in task_runs} == {'browser-device', 'browser-device-2'}
                        assert len({r['batch_id'] for r in task_runs}) == 1
                        assert all(r['live'] for r in task_runs)
                        expect(page.locator('.el-message-box:visible')).to_have_count(0)
                        page.screenshot(path=str(args.artifacts / 'tasks-workbench.png'), full_page=True)
                        record('UI-09', '离线设备禁选，两在线设备独立启动', '页面保存任务并选两设备启动，同一批次产生两个 live 运行')
                        begin('UI-10')
                        # Pause/cancel is independent per run; the other device keeps running.
                        first, second = task_runs
                        dialog.locator('.result-row').filter(has=page.get_by_text(first['serial'],exact=True)).get_by_role('button', name='查看运行', exact=True).click()
                        expect(panel.get_by_role('button', name='暂停', exact=True)).to_be_enabled()
                        panel.get_by_role('button', name='暂停', exact=True).click()
                        wait_status(first['id'], 'paused')
                        assert api('/api/runs/' + second['id'])['status'] == 'running'
                        panel.get_by_role('button', name='停止', exact=True).click()
                        wait_status(first['id'], 'cancelled')
                        panel.locator('.el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text=second['id']).click()
                        panel.get_by_role('button', name='停止', exact=True).click()
                        wait_status(second['id'], 'cancelled')
                        page.reload()
                        expect(page.get_by_text('API 在线', exact=True)).to_be_visible()
                        page.get_by_role('button', name='任务', exact=True).click()
                        expect(page.locator('.task-card')).to_have_count(1)
                        assert len([r for r in api('/api/runs') if r.get('task_id') == task['id']]) == 2
                        assert not errors, errors
                        record('UI-10', '一台暂停不影响另一台，页面独立停止并保留历史', '页面暂停设备一时设备二 running；分别停止后刷新仍有两条历史')
                        begin('UI-11')
                        # Legacy or missing capture links cannot leave an unrelated screenshot visible.
                        for capture_link in [None, 'missing-original']:
                            payload = {'id': 'capture-edge', 'name': '原图异常验证', 'recognition': {'type': 'text', 'texts': ['OK']}}
                            if capture_link:
                                payload['workbench'] = {'capture_id': capture_link}
                            assert page.request.post(base + '/api/states', data=payload).ok
                            page.reload()
                            expect(page.get_by_text('API 在线', exact=True)).to_be_visible()
                            page.locator('.state-card').filter(has_text=state_id).click()
                            expect(canvas).to_be_visible()
                            page.locator('.state-card').filter(has_text='capture-edge').click()
                            expect(canvas).not_to_be_visible()
                            if capture_link:
                                expect(drawer.locator('.el-alert--error')).to_contain_text('完整截图不存在或加载失败')
                            else:
                                expect(page.get_by_text('此 State 尚未关联完整截图，请重新导入原图并保存一次。', exact=True)).to_be_visible()
                            assert page.request.post(base + '/api/states/delete', data={'id': 'capture-edge'}).ok
                        assert not errors, errors
                        record('UI-11', '原图缺失时清除旧截图并说明原因', '无关联和丢失关联两种场景均无残留截图，错误提示可见')
                        begin('UI-12')
                        race_state = {'id':'import-race','name':'另一编辑状态','recognition':original['recognition']}
                        assert page.request.post(base + '/api/states', data=race_state).ok
                        page.reload()
                        expect(page.get_by_text('API 在线', exact=True)).to_be_visible()
                        page.locator('.state-card').filter(has_text=state_id).click()
                        name_before = field(drawer, '名称').locator('input').input_value()
                        page.evaluate("""() => { const originalFetch=window.fetch; window.restoreBusinessFetch=()=>{window.fetch=originalFetch;};
                            window.fetch=async(...args)=>{if(['/api/import','/api/capture'].includes(args[0]))await new Promise(r=>setTimeout(r,800));return originalFetch(...args);}; }""")
                        with page.expect_response(lambda r:r.url.endswith('/api/import')):
                            page.locator('input[type=file]').set_input_files(data / 'browser-page.png')
                            expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_disabled()
                            expect(page.get_by_text('正在处理请求，请稍候。', exact=True)).to_be_visible()
                            page.locator('.state-card').filter(has_text='import-race').click()
                            expect(field(drawer, '名称').locator('input')).to_have_value(name_before)
                        expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_enabled()
                        page.locator('.toolbar .el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text=re.compile('^browser-device ·')).click()
                        with page.expect_response(lambda r:r.url.endswith('/api/capture')):
                            page.get_by_role('button', name='设备截图 F1', exact=True).click()
                            expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_disabled()
                            page.locator('.state-card').filter(has_text='import-race').click()
                            expect(field(drawer, '名称').locator('input')).to_have_value(name_before)
                        expect(drawer.get_by_role('button', name='保存 State', exact=True)).to_be_enabled()
                        page.evaluate('window.restoreBusinessFetch()')
                        assert page.request.post(base + '/api/states/delete', data={'id':'import-race'}).ok
                        record('UI-12', '导入/截图期间不得切换编辑上下文', '两种延迟请求期间保存禁用，点击另一 State 均未切换，返回后仍是原编辑状态；另有模型测试验证启动防重')
                        begin('UI-13')
                        page.get_by_role('button', name='循环流程', exact=True).click()
                        page.locator('.flow-card').filter(has=page.get_by_text('收货循环',exact=True)).click()
                        with page.expect_response(lambda r:r.url.endswith('/api/debug/start')) as step:
                            form.get_by_role('button', name='步进调试', exact=True).click()
                        assert step.value.ok, step.value.text()
                        step_id = step.value.json()['results'][0]['id']
                        wait_status(step_id, 'waiting')
                        expect(panel.get_by_role('button', name='执行下一步', exact=True)).to_be_enabled()
                        panel.get_by_role('button', name='执行下一步', exact=True).click()
                        for _ in range(150):
                            detail = api('/api/runs/' + step_id)
                            if detail['status']=='waiting' and detail['rounds']==1:break
                            page.wait_for_timeout(50)
                        assert detail['status']=='waiting' and detail['rounds']==1, detail
                        page.wait_for_timeout(200)
                        assert api('/api/runs/' + step_id)['rounds']==1
                        expect(panel.get_by_role('button', name='执行下一步', exact=True)).to_be_enabled()
                        page.screenshot(path=str(args.artifacts / 'step-waiting.png'), full_page=True)
                        panel.get_by_role('button', name='切换自动执行', exact=True).click()
                        wait_status(step_id, 'running')
                        panel.get_by_role('button', name='停止', exact=True).click()
                        wait_status(step_id, 'cancelled')
                        expect(panel.locator('.run-summary')).to_contain_text('cancelled')
                        record('UI-13', '页面可启动步进且只运行一轮、可切换自动并停止', '页面点击步进调试，下一步后恰好一轮，再切自动并停止成功')
                        assert not errors, errors
                        print('Chromium smoke passed: State, recognition, flows, tasks, request isolation and step controls; no page errors')
                    finally:
                        if sys.exc_info()[0] is not None:
                            cases.append({'case_id':active_case,'status':'失败','actual':str(sys.exc_info()[1])})
                            try:
                                page.screenshot(path=str(args.artifacts / 'failure.png'), full_page=True)
                            except PlaywrightError:
                                pass
                        (args.artifacts / 'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
                        (args.artifacts / 'network.json').write_text(json.dumps(network,ensure_ascii=False,indent=2),encoding='utf-8')
                        (args.artifacts / 'technical.json').write_text(json.dumps({'page_errors':errors,'events':technical},ensure_ascii=False,indent=2),encoding='utf-8')
                        browser.close()
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


if __name__ == '__main__':
    main()
