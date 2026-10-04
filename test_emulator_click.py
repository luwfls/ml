"""Test if dm input actually works on Android emulator."""
import time
import win32com.client
import pythoncom

def test_click(hwnd):
    """Test clicking in the emulator window."""
    pythoncom.CoInitialize()
    try:
        dm = win32com.client.Dispatch("dm.dmsoft")
        print(f"dm.dll version: {dm.Ver()}")

        # Bind with current config
        result = dm.BindWindow(hwnd, "gdi", "windows", "windows", 0)
        if result != 1:
            print(f"✗ BindWindow failed: {result}")
            return False

        print("✓ Bound successfully")
        print("\nTesting click at (500, 300)...")
        print("Watch the emulator window for click feedback")

        # Move and click
        dm.MoveTo(500, 300)
        time.sleep(0.5)

        # Click sequence
        dm.LeftDown()
        dm.Delay(50)
        dm.LeftUp()

        print("✓ Click sent via dm.dll")
        print("\nDid you see any response in the emulator? (Y/N)")

        dm.UnBindWindow()
        return True

    except Exception as e:
        print(f"✗ Exception: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    hwnd = 15337536  # Android Device window

    print("=" * 60)
    print("Make sure the Android Device window is visible!")
    print("=" * 60)
    print("\nWaiting 3 seconds before clicking...")
    time.sleep(3)

    test_click(hwnd)
