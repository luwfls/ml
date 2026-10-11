import json
import threading
from pathlib import Path

import numpy as np


class RapidOcrProvider:
    """Shared CPU engine; recognition calls are serialized across HTTP/run threads."""

    def __init__(self, config_path=None):
        import rapidocr

        params = {
            'Global.text_score': 0,
            'EngineConfig.onnxruntime.use_cuda': False,
            'EngineConfig.onnxruntime.use_dml': False,
            'EngineConfig.onnxruntime.use_cann': False,
            'EngineConfig.onnxruntime.use_coreml': False,
            'EngineConfig.onnxruntime.intra_op_num_threads': 2,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        }
        if config_path is None:
            base = Path(rapidocr.__file__).resolve().parent / 'models'
            data = {'det_model': 'PP-OCRv6_det_small.onnx', 'cls_model': 'ch_ppocr_mobile_v2.0_cls_mobile.onnx',
                    'rec_model': 'PP-OCRv6_rec_small.onnx'}
        else:
            config_path = Path(config_path).expanduser().resolve()
            base = config_path.parent
            data = json.loads(config_path.read_text(encoding='utf-8'))
        allowed = {'det_model', 'cls_model', 'rec_model', 'rec_keys'}
        if not isinstance(data, dict) or set(data) - allowed:
            raise ValueError('OCR 配置仅支持 det_model/cls_model/rec_model/rec_keys')
        for key, target in [('det_model', 'Det.model_path'), ('cls_model', 'Cls.model_path'),
                            ('rec_model', 'Rec.model_path'), ('rec_keys', 'Rec.rec_keys_path')]:
            if key == 'rec_keys' and key not in data:
                continue
            value = data.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f'OCR 配置缺少本地文件: {key}')
            path = (base / Path(value).expanduser()).resolve()
            if not path.is_file():
                raise ValueError(f'OCR 本地文件不存在: {key}: {path}')
            params[target] = str(path)
        if config_path is not None and 'rec_keys' not in data:
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(params['Rec.model_path'], sess_options=options, providers=['CPUExecutionProvider'])
            if not session.get_modelmeta().custom_metadata_map.get('character'):
                raise ValueError('自定义识别模型没有内嵌字典，请配置本地 rec_keys；禁止自动下载字典')
        self.engine = rapidocr.RapidOCR(params=params)
        self.lock = threading.Lock()

    def __call__(self, frame):
        with self.lock:
            output = self.engine(frame)
        boxes, texts, scores = output.boxes, output.txts, output.scores
        if boxes is None and texts is None and scores is None:
            return []
        if any(value is None for value in (boxes, texts, scores)) or not len(boxes) == len(texts) == len(scores):
            raise ValueError('OCR 返回的文字、置信度和坐标数量不一致')
        height, width = frame.shape[:2]
        items = []
        for box, text, confidence in zip(boxes, texts, scores):
            points = np.asarray(box, dtype=float)
            confidence = float(confidence)
            if points.shape != (4, 2) or not np.isfinite(points).all() or not np.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError('OCR 返回无效坐标或置信度')
            lower = np.maximum(np.floor(points.min(axis=0)), [0, 0]).astype(int)
            upper = np.minimum(np.ceil(points.max(axis=0)), [width, height]).astype(int)
            if not isinstance(text, str) or not text.strip() or np.any(lower >= upper):
                raise ValueError('OCR 返回空文字或无效识别框')
            items.append({'text': text, 'confidence': confidence, 'bbox': [int(lower[0]), int(lower[1]), int(upper[0]), int(upper[1])]})
        return items
