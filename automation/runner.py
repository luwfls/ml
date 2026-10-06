import threading
import time

from .state import number, validate_state


def validate_flow(flow, states):
    known = {s['id']: s for s in states}
    ids = flow.get('state_ids')
    if not isinstance(ids, list) or not ids or any(s not in known for s in ids):
        raise ValueError('流程必须引用存在的 State')
    number(flow.get('max_rounds', 200), 1, 10000)
    number(flow.get('timeout_seconds', 300), .01, 3600)
    number(flow.get('poll_ms', 1000), 0, 10000)
    number(flow.get('completion_count', 1), 1, 1000)
    for key in ['max_rounds', 'completion_count', 'poll_ms']:
        value = flow.get(key, {'max_rounds': 200, 'completion_count': 1, 'poll_ms': 1000}[key])
        if not isinstance(value, int):
            raise ValueError(f'{key} 必须为整数')
    for state in states:
        for ref in state['conditions']['required_states'] + state['conditions']['excluded_states']:
            if ref not in known:
                raise ValueError(f'条件引用不存在: {ref}')
    if not any(known[s]['role'] == 'success' for s in ids):
        raise ValueError('首版流程至少需要一个成功 State')
    return known


class RunControl:
    def __init__(self, cancel, notify):
        self.cancel = cancel
        self.notify = notify
        self.condition = threading.Condition()
        self.requested = False
        self.paused = False

    def pause(self):
        with self.condition:
            if self.requested: return
            self.requested = True
            self.notify('pausing')
            self.condition.notify_all()

    def resume(self):
        with self.condition:
            if not self.paused:
                raise ValueError('只有仍在运行的用户暂停可以继续')
            self.requested = False
            self.condition.notify_all()

    def checkpoint(self):
        with self.condition:
            if not self.requested or self.cancel.is_set(): return 0
            started = time.monotonic()
            self.paused = True
            self.notify('paused')
            while self.requested and not self.cancel.is_set():
                self.condition.wait(.02)
            self.paused = False
            if not self.cancel.is_set(): self.notify('running')
            return time.monotonic() - started


def run_loop(states, flow, device, matcher, cancel=None, emit=None, control=None):
    cancel = cancel or threading.Event()
    emit = emit or (lambda event: None)
    states = [validate_state(s) for s in states]
    known = validate_flow(flow, states)
    candidates = sorted([known[s] for s in set(flow['state_ids'])], key=lambda s: (-s['priority'], s['id']))
    deadline = time.monotonic() + flow.get('timeout_seconds', 300)
    def checkpoint():
        nonlocal deadline
        if control is not None:
            duration = control.checkpoint()
            deadline += duration
            return duration > 0
        return False

    def wait(seconds):
        remaining = seconds
        while remaining > 0 and not cancel.is_set():
            checkpoint()
            started = time.monotonic()
            cancel.wait(min(.02, remaining, max(0, deadline - started)))
            remaining -= time.monotonic() - started
            if time.monotonic() >= deadline: break

    count, previous_success, last_action = 0, False, None
    result = {'status': 'failed', 'reason': 'max_rounds', 'success_count': 0, 'dry_run': bool(flow.get('dry_run', False))}
    round_index = 0
    while round_index < flow.get('max_rounds', 200):
        checkpoint()
        if cancel.is_set():
            result.update(status='cancelled', reason='user_cancelled')
            break
        if time.monotonic() >= deadline:
            result['reason'] = 'timeout'
            break
        frame = device.capture()
        matcher.begin(frame)
        hits = []
        for state in candidates:
            match = matcher.match(frame, state)
            conditions = state['conditions']
            eligible = match['found'] and all(matcher.match(frame, known[s])['found'] for s in conditions['required_states'])
            eligible = eligible and not any(matcher.match(frame, known[s])['found'] for s in conditions['excluded_states'])
            emit({'type': 'probe', 'round': round_index + 1, 'state_id': state['id'], 'eligible': eligible, **match})
            if eligible:
                hits.append((state, match))
        if checkpoint(): continue
        if cancel.is_set(): break
        if time.monotonic() >= deadline:
            result['reason'] = 'timeout'
            break
        successes = [s for s, m in hits if s['role'] == 'success']
        failures = [s for s, m in hits if s['role'] == 'failure']
        if successes and failures:
            result.update(status='paused', reason='conflicting_terminal_states')
            break
        if failures:
            result['reason'] = 'failure_state'
            break
        if successes and not previous_success:
            count += 1
            emit({'type': 'success', 'count': count})
        previous_success = bool(successes)
        result['success_count'] = count
        if count >= flow.get('completion_count', 1):
            result.update(status='passed', reason='completion_count_reached')
            break
        normal = [(s, m) for s, m in hits if s['role'] == 'normal']
        selected = normal or [(s, m) for s, m in hits if s['role'] == 'fallback']
        action_state = selected[0][0]['id'] if selected else None
        if selected and action_state != last_action:
            state, match = selected[0]
            if match.get('ambiguous') and any(a['type'] == 'click_match' for a in state['actions']):
                result.update(status='paused', reason='ambiguous_match')
                break
            restart = False
            for action in state['actions']:
                if checkpoint() and action['type'] != 'wait':
                    restart = True
                    break
                if cancel.is_set() or time.monotonic() >= deadline:
                    break
                emit({'type': 'action', 'state_id': state['id'], 'action': action, 'bbox': match['bbox']})
                if action['type'] == 'wait':
                    wait(min(action.get('ms', 500) / 1000, max(0, deadline - time.monotonic())))
                elif not flow.get('dry_run', False):
                    device.execute(action, match, frame)
            if restart: continue
        last_action = action_state
        round_index += 1
        wait(min(flow.get('poll_ms', 1000) / 1000, max(0, deadline - time.monotonic())))
    if cancel.is_set():
        result.update(status='cancelled', reason='user_cancelled')
    emit({'type': 'result', **result})
    return result
