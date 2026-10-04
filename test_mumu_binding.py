"""测试 MuMu 模拟器窗口绑定"""
from game_bot.scripted.runner import find_default_game_window, prepare_game_window, list_scripts
from game_bot.core.capture import capture_client_to_file

def test_window_binding():
    print("=" * 60)
    print("测试 MuMu 模拟器窗口绑定")
    print("=" * 60)

    # 1. 测试窗口查找
    print("\n1. 查找游戏窗口...")
    hwnd = find_default_game_window()
    print(f"   ✓ 找到窗口: hwnd={hwnd}")

    # 2. 测试窗口准备
    print("\n2. 准备窗口...")
    info = prepare_game_window(hwnd)
    print(f"   ✓ 窗口标题: {info.title}")
    print(f"   ✓ 窗口位置: ({info.window_rect.left}, {info.window_rect.top})")
    print(f"   ✓ 客户区尺寸: {info.client_size.width}x{info.client_size.height}")

    # 3. 测试截图
    print("\n3. 测试截图...")
    result = capture_client_to_file(hwnd, 'runtime/test/mumu_binding_test.png', backend='auto')
    print(f"   ✓ 截图成功: {result.path}")
    print(f"   ✓ 截图尺寸: {result.size.width}x{result.size.height}")

    # 4. 列出可用脚本
    print("\n4. 可用脚本:")
    scripts = list_scripts()
    for i, script in enumerate(scripts[:10], 1):
        print(f"   {i}. {script}")
    if len(scripts) > 10:
        print(f"   ... 还有 {len(scripts) - 10} 个脚本")

    print("\n" + "=" * 60)
    print("✓ 所有测试通过！MuMu 模拟器窗口绑定正常工作。")
    print("=" * 60)

if __name__ == "__main__":
    test_window_binding()
