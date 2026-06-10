"""Quick test of the telemetry collector without iRacing"""

import asyncio
from racecraft.detection import GameDetector

async def test_detection():
    """Test game detection"""
    detector = GameDetector()

    print("Testing game detection...")
    print("Supported games:")
    for proc_name, config in detector.GAME_CONFIGS.items():
        print(f"  - {config['name']} ({proc_name})")

    print("\nScanning for running games...")
    result = await detector.detect_active_game()

    if result:
        print(f"✓ Found game: {result['name']}")
        print(f"  Protocol: {result['protocol']}")
        print(f"  Update rate: {result['update_rate']} Hz")
    else:
        print("✗ No racing games detected")
        print("\nTo test with iRacing:")
        print("  1. Launch iRacing")
        print("  2. Run: python -m racecraft.app")
        print("  3. Watch the UI update with live telemetry!")

if __name__ == "__main__":
    asyncio.run(test_detection())
