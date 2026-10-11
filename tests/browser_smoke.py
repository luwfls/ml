"""Real Chromium workbench smoke test with a foreground fake-device backend.

Run with a Python environment containing playwright and --python pointing at
the project's environment. Build the frontend first. No actual ADB is invoked.
"""
import argparse
import json
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright, expect


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
                        page.get_by_role('button', name='新建 State', exact=True).click()
                        drawer = page.locator('.el-drawer:visible')
                        field(drawer, 'ID').locator('input').fill('confirm')
                        field(drawer, '名称').locator('input').fill('确认收货')
                        field(drawer, '角色').locator('.el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text=re.compile('success|成功断言')).click()
                        drawer.get_by_role('button', name='保存 F4', exact=True).click()
                        expect(page.locator('.state-card').filter(has_text='confirm')).to_be_visible()
                        assert api('/api/states')[0]['group'] == '收货验证'
                        drawer.get_by_role('button', name='识别预览', exact=True).click()
                        expect(page.locator('.preview-results')).to_contain_text('命中')
                        drawer.locator('.el-drawer__close-btn').click()
                        page.screenshot(path=str(args.artifacts / 'state-workbench.png'), full_page=True)
                        # Prompt has already been shown: hidden dialog must not disable F6.
                        canvas.click(position={'x': 10, 'y': 10})
                        with page.expect_response(lambda r: r.url.endswith('/api/preview-group')):
                            page.keyboard.press('F6')
                        assert not errors, errors

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
                        drawer.locator('.el-drawer__close-btn').click()
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
                        drawer.get_by_role('button', name='保存 F4', exact=True).click()
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

                        page.get_by_role('button', name='循环流程', exact=True).click()
                        form = page.locator('.flow-layout .el-card').nth(1)
                        field(form, '流程 ID').locator('input').fill('receive-loop')
                        field(form, '名称').locator('input').fill('收货循环')
                        field(form, '完成次数').locator('input').fill('2')
                        field(form, '轮间等待 ms').locator('input').fill('100')
                        field(form, '超时（秒）').locator('input').fill('30')
                        field(form, '按分组添加').locator('.el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text='收货验证').click()
                        form.get_by_role('button', name='添加当前分组', exact=True).click()
                        form.get_by_role('button', name='保存流程', exact=True).click()
                        expect(page.locator('.flow-card').filter(has_text='receive-loop')).to_be_visible()
                        form.get_by_role('button', name='复制', exact=True).click()
                        prompt('receive-copy')
                        expect(page.locator('.flow-card').filter(has_text='receive-copy')).to_be_visible()
                        assert len(api('/api/flows')) == 2
                        page.locator('.flow-card').filter(has_text='receive-loop').click()
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
                        page.get_by_role('button', name='任务', exact=True).click()
                        tasks = page.locator('.task-panel')
                        tasks.get_by_role('button', name='新建任务', exact=True).click()
                        field(tasks, '任务名称').locator('input').fill('多设备收货验证')
                        field(tasks, '关联流程').locator('.el-select').click()
                        page.locator('.el-select-dropdown__item:visible').filter(has_text=re.compile('^收货循环 · receive-loop$')).click()
                        tasks.get_by_role('button', name='保存任务', exact=True).click()
                        expect(tasks.locator('.task-card')).to_have_count(1)
                        task = api('/api/tasks')[0]
                        assert task['id'] and task['flow_id'] == 'receive-loop'
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
                        # Pause/cancel is independent per run; the other device keeps running.
                        first, second = task_runs
                        response = page.request.post(base + '/api/pause', data={'id': first['id']})
                        assert response.ok
                        wait_status(first['id'], 'paused')
                        assert api('/api/runs/' + second['id'])['status'] == 'running'
                        for run in task_runs:
                            assert page.request.post(base + '/api/cancel', data={'id': run['id']}).ok
                            wait_status(run['id'], 'cancelled')
                        page.reload()
                        expect(page.get_by_text('API 在线', exact=True)).to_be_visible()
                        page.get_by_role('button', name='任务', exact=True).click()
                        expect(page.locator('.task-card')).to_have_count(1)
                        assert len([r for r in api('/api/runs') if r.get('task_id') == task['id']]) == 2
                        assert not errors, errors
                        print('Chromium smoke passed: State/flow editing, task save and two-device launch, independent pause/cancel, reload and evidence; no page errors')
                    finally:
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
