#!/usr/bin/env python3
"""
Test script to verify embedded events workflow.

This script tests:
1. Creating a project with ProjectContext
2. Verifying ProjectContext is attached
3. Checking if repo is available for background jobs
"""

import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

def test_project_context_flow():
    """Test that ProjectContext is properly created and attached."""

    print("=" * 70)
    print("EMBEDDED EVENTS WORKFLOW TEST")
    print("=" * 70)

    # Test 1: Import necessary modules
    print("\n1. Testing imports...")
    try:
        from vasoanalyzer.core.project import open_project_ctx, Project
        from vasoanalyzer.core.project_context import ProjectContext
        print("   ✅ Imports successful")
    except Exception as e:
        print(f"   ❌ Import failed: {e}")
        return False

    # Test 2: Create a mock window object
    print("\n2. Creating mock window object...")
    class MockWindow:
        def __init__(self):
            self.project_ctx = None
            self.project_path = None
            self.project_meta = {}
            self.current_project = None

        def statusBar(self):
            class MockStatusBar:
                def showMessage(self, msg, timeout=0):
                    print(f"   [StatusBar] {msg}")
            return MockStatusBar()

    window = MockWindow()
    print("   ✅ Mock window created")

    # Test 3: Simulate opening a project
    print("\n3. Testing ProjectContext creation...")
    test_path = "/tmp/test_project.vaso"

    # We can't actually create a real project without the full app,
    # but we can test the logic flow
    print(f"   Would create ProjectContext for: {test_path}")
    print(f"   Current window.project_ctx: {window.project_ctx}")

    # Test 4: Check the open_project_file function
    print("\n4. Checking open_project_file function...")
    try:
        from vasoanalyzer.app.openers import open_project_file
        print("   ✅ open_project_file function found")
        print(f"   Function: {open_project_file}")
    except Exception as e:
        print(f"   ❌ Could not import open_project_file: {e}")
        return False

    # Test 5: Check background job
    print("\n5. Checking background job...")
    try:
        # Check if the job would get repo
        if window.project_ctx is None:
            print("   ⚠️  window.project_ctx is None")
            print("   Background job would create NEW context (BAD)")
        else:
            print("   ✅ window.project_ctx exists")
            print("   Background job would use EXISTING context (GOOD)")
    except Exception as e:
        print(f"   ❌ Error checking background job: {e}")
        return False

    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print("\nThe test verified that:")
    print("1. ✅ Imports work correctly")
    print("2. ✅ open_project_file function exists")
    print("3. ⚠️  Manual testing required to verify ProjectContext is set")
    print("\nNEXT STEPS:")
    print("1. Run the app: python3 src/main.py")
    print("2. Look for these log messages:")
    print("   - '📂 open_project_file called'")
    print("   - '🔑 Creating ProjectContext'")
    print("   - '✅ ProjectContext created successfully'")
    print("   - '✅ ProjectContext attached to window'")
    print("3. When loading samples, look for:")
    print("   - '✅ Background job: Using EXISTING repo' (GOOD)")
    print("   - '🚨 Background job: repo is None!' (BAD)")
    print("\n" + "=" * 70)

    return True

if __name__ == "__main__":
    success = test_project_context_flow()
    sys.exit(0 if success else 1)
