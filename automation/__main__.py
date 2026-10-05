import argparse
import struct
from pathlib import Path

from .state import Store
from .web import create_server


def main():
    if struct.calcsize('P') * 8 != 64:
        raise SystemExit('请使用 Python 64 位解释器')
    parser = argparse.ArgumentParser(description='安卓 State 自动化工作台')
    parser.add_argument('--data', type=Path, default=Path('data'))
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--ocr-config', type=Path, help='本地 OCR 模型 JSON 配置；不指定时使用锁定版本随包提供的模型')
    parser.add_argument('--no-ocr', action='store_true', help='仅图片模式，不加载 OCR')
    args = parser.parse_args()
    if args.no_ocr and args.ocr_config:
        parser.error('--no-ocr 和 --ocr-config 不能同时使用')
    provider = None
    if not args.no_ocr:
        from .ocr import RapidOcrProvider
        print('加载本地 RapidOCR CPU 模型', flush=True)
        provider = RapidOcrProvider(args.ocr_config)
    server = create_server(Store(args.data), args.port, args.adb, ocr=provider)
    print(f'工作台 http://127.0.0.1:{server.server_port}；OCR {"RapidOCR CPU" if provider else "disabled"}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop_runs()
        server.server_close()


if __name__ == '__main__':
    main()
