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


def run_loop(states, flow, device, matcher, cancel=None, emit=None):
    cancel = cancel or threading.Event()
    emit = emit or (lambda event: None)
    states = [validate_state(s) for s in states]
    known = validate_flow(flow, states)
    candidates = sorted([known[s] for s in set(flow['state_ids'])], key=lambda s: (-s['priority'], s['id']))
    deadline = time.monotonic() + flow.get('timeout_seconds', 300)
    count, previous_success, last_action = 0, False, None
    result = {'status': 'failed', 'reason': 'max_rounds', 'success_count': 0, 'dry_run': bool(flow.get('dry_run', False))}
    for round_index in range(flow.get('max_rounds', 200)):
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
            for action in state['actions']:
                if cancel.is_set() or time.monotonic() >= deadline:
                    break
                emit({'type': 'action', 'state_id': state['id'], 'action': action, 'bbox': match['bbox']})
                if action['type'] == 'wait':
                    cancel.wait(min(action.get('ms', 500) / 1000, max(0, deadline - time.monotonic())))
                elif not flow.get('dry_run', False):
                    device.execute(action, match, frame)
        last_action = action_state
        cancel.wait(min(flow.get('poll_ms', 1000) / 1000, max(0, deadline - time.monotonic())))
    if cancel.is_set():
        result.update(status='cancelled', reason='user_cancelled')
    emit({'type': 'result', **result})
    return result
