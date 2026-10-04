"""
检查窗口层级和子窗口
"""
import sys
from pathlib import Path
from ctypes import windll, WINFUNCTYPE, c_int, c_long, c_void_p, c_wchar_p, byref, create_unicode_buffer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from game_bot.core.window import find_window_by_title, get_client_size
from game_bot.config.loader import load_settings


# 枚举子窗口回调
EnumWindowsProc = WINFUNCTYPE(c_int, c_long, c_void_p)


def enum_child_windows(parent_hwnd):
    """枚举所有子窗口"""
    children = []

    def callback(hwnd, _):
        children.append(hwnd)
        return 1

    windll.user32.EnumChildWindows(parent_hwnd, EnumWindowsProc(callback), 0)
    return children


def get_window_text(hwnd):
    """获取窗口标题"""
    length = windll.user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buffer = create_unicode_buffer(length + 1)
    windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def get_window_class(hwnd):
    """获取窗口类名"""
    buffer = create_unicode_buffer(256)
    windll.user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def check_window_hierarchy():
    """检查窗口层级"""
    print("=" * 80)
    print("窗口层级检查")
    print("=" * 80)

    # 查找主窗口
    settings = load_settings()
    window_title = settings.get("game", {}).get("window_title", "Android Device")

    try:
        main_hwnd = find_window_by_title(window_title)
    except Exception as e:
        print(f"错误: {e}")
        return

    print(f"\n主窗口:")
    print(f"  hwnd: {main_hwnd:#x}")
    print(f"  标题: {get_window_text(main_hwnd)}")
    print(f"  类名: {get_window_class(main_hwnd)}")
    size = get_client_size(main_hwnd)
    print(f"  尺寸: {size.width}×{size.height}")

    # 枚举子窗口
    children = enum_child_windows(main_hwnd)

    if not children:
        print(f"\n没有子窗口")
        print(f"\n>>> 应该直接绑定主窗口: {main_hwnd:#x}")
    else:
        print(f"\n找到 {len(children)} 个子窗口:")

        for i, child_hwnd in enumerate(children, 1):
            title = get_window_text(child_hwnd)
            classname = get_window_class(child_hwnd)

            # 获取子窗口尺寸
            rect = (c_long * 4)()
            windll.user32.GetClientRect(child_hwnd, rect)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]

            print(f"\n  子窗口 {i}:")
            print(f"    hwnd: {child_hwnd:#x}")
            print(f"    标题: '{title}' (空则无标题)")
            print(f"    类名: {classname}")
            print(f"    尺寸: {width}×{height}")

            # 判断是否是渲染窗口
            if width > 0 and height > 0:
                print(f"    >>> 这可能是实际渲染窗口！")

        # 找到最大的子窗口
        max_child = None
        max_area = 0

        for child_hwnd in children:
            rect = (c_long * 4)()
            windll.user32.GetClientRect(child_hwnd, rect)
            width = rect[2] - rect[0]
            height = rect[3] - rect[1]
            area = width * height

            if area > max_area:
                max_area = area
                max_child = child_hwnd

        if max_child:
            print(f"\n最大的子窗口: {max_child:#x}")
            print(f">>> 建议绑定这个子窗口而不是主窗口")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    check_window_hierarchy()
