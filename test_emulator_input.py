"""Test dm input on Android emulator with different bind modes."""
import win32com.client
import pythoncom

def test_dm_bind(hwnd, display="gdi", mouse="windows", keypad="windows", mode=0):
    """Test dm.dll binding with specified parameters."""
    pythoncom.CoInitialize()
    try:
        dm = win32com.client.Dispatch("dm.dmsoft")
        print(f"dm.dll version: {dm.Ver()}")
        print(f"Testing bind: hwnd={hwnd}, display={display}, mouse={mouse}, keypad={keypad}, mode={mode}")

        result = dm.BindWindow(hwnd, display, mouse, keypad, mode)
        print(f"BindWindow result: {result}")

        if result == 1:
            print("✓ Bind successful, testing mouse move...")
            dm.MoveTo(100, 100)
            print("✓ MoveTo(100, 100) executed")
            dm.UnBindWindow()
            return True
        else:
            print(f"✗ Bind failed with result={result}")
            return False
    except Exception as e:
        print(f"✗ Exception: {e}")
        return False
    finally:
        pythoncom.CoUninitialize()

if __name__ == "__main__":
    hwnd = 15337536  # Android Device window

    print("=" * 60)
    print("Test 1: Current config (windows mode, bind_mode=0)")
    print("=" * 60)
    test_dm_bind(hwnd, display="gdi", mouse="windows", keypad="windows", mode=0)

    print("\n" + "=" * 60)
    print("Test 2: Backend mode (normal, bind_mode=101)")
    print("=" * 60)
    test_dm_bind(hwnd, display="normal", mouse="normal", keypad="normal", mode=101)

    print("\n" + "=" * 60)
    print("Test 3: Backend mode (gdi, bind_mode=101)")
    print("=" * 60)
    test_dm_bind(hwnd, display="gdi", mouse="normal", keypad="normal", mode=101)

    print("\n" + "=" * 60)
    print("Test 4: Backend mode with dx (bind_mode=103)")
    print("=" * 60)
    test_dm_bind(hwnd, display="gdi", mouse="normal", keypad="normal", mode=103)
