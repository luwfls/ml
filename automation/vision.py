import unicodedata

import cv2

from .state import validate_state


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC', text).split())


def match_text(text, choices, mode):
    text = normalize(text)
    scores = []
    for choice in choices:
        choice = normalize(choice)
        if mode == 'exact':
            score = float(text == choice)
        elif mode == 'contains':
            score = float(choice in text)
        else:
            previous = list(range(len(choice) + 1))
            for i, a in enumerate(text, 1):
                current = [i]
                for j, b in enumerate(choice, 1):
                    current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
                previous = current
            score = 1 - previous[-1] / max(len(text), len(choice), 1)
        scores.append(score)
    return max(scores, default=0)


class Recognizer:
    def __init__(self, store, ocr=None):
        self.store = store
        self.ocr = ocr
        self.frame = None
        self.ocr_items = None
        self.results = {}
        self.templates = {}

    def begin(self, frame):
        self.frame = frame
        self.ocr_items = None
        self.results = {}

    def match(self, frame, data):
        if self.frame is not frame:
            self.begin(frame)
        data = validate_state(data)
        if data['id'] in self.results:
            return self.results[data['id']]
        recognition = data['recognition']
        height, width = frame.shape[:2]
        left, top, right, bottom = [int(v * size) for v, size in zip(recognition['region'], [width, height, width, height])]
        result = {'found': False, 'bbox': None, 'score': 0, 'ambiguous': False, 'state_id': data['id']}
        if right <= left or bottom <= top:
            raise ValueError('ROI 在当前截图上为空')
        if recognition['type'] == 'image':
            path = self.store.assets / recognition['asset']
            version = (path.stat().st_mtime_ns, path.stat().st_size)
            cached = self.templates.get(str(path))
            if cached is None or cached[0] != version:
                image = cv2.imread(str(path))
                if image is None or cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).std() < 1:
                    raise ValueError('模板无效或缺少可识别的纹理')
                cached = (version, image)
                self.templates[str(path)] = cached
            template = cached[1]
            search = frame[top:bottom, left:right]
            boxes = []
            for scale in recognition['scales']:
                scaled = cv2.resize(template, None, fx=scale, fy=scale)
                h, w = scaled.shape[:2]
                if h > search.shape[0] or w > search.shape[1]:
                    continue
                response = cv2.matchTemplate(search, scaled, cv2.TM_CCOEFF_NORMED)
                _, score, _, point = cv2.minMaxLoc(response)
                # Suppress overlapping placements before checking for another button.
                for _ in range(2):
                    _, candidate_score, _, candidate_point = cv2.minMaxLoc(response)
                    if candidate_score < recognition['threshold']:
                        break
                    x, y = candidate_point
                    box = [left + x, top + y, left + x + w, top + y + h]
                    if not any(min(box[2], old[2]) > max(box[0], old[0]) and min(box[3], old[3]) > max(box[1], old[1]) for old in boxes):
                        boxes.append(box)
                    response[max(0, y - h + 1):y + h, max(0, x - w + 1):x + w] = -1
                if score > result['score']:
                    x, y = point
                    result.update(score=score, bbox=[left + x, top + y, left + x + w, top + y + h])
            result['found'] = result['score'] >= recognition['threshold']
            result['ambiguous'] = len(boxes) > 1
        else:
            if self.ocr is None:
                raise RuntimeError('OCR 未配置，请启用 RapidOCR 后识别文字 State')
            if self.ocr_items is None:
                self.ocr_items = self.ocr(frame)
            candidates = []
            for item in self.ocr_items:
                x1, y1, x2, y2 = item['bbox']
                if not (left <= x1 < x2 <= right and top <= y1 < y2 <= bottom):
                    continue
                score = match_text(item['text'], recognition['texts'], recognition['mode'])
                if item['confidence'] >= recognition['min_confidence'] and score >= recognition['similarity_threshold']:
                    candidates.append({**item, 'score': score})
            if candidates:
                best = max(candidates, key=lambda item: item['score'])
                result.update(found=True, bbox=best['bbox'], score=best['score'], text=best['text'],
                              confidence=best['confidence'], ambiguous=len(candidates) > 1)
        self.results[data['id']] = result
        return result
