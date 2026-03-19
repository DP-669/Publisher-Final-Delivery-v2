from engine import IngestionEngine
from pathlib import Path

def test_engine():
    print("Testing Ingestion Engine (Pathlib & Specific User Path)...")
    
    # Initialize Engine - Checks Default Path
    engine = IngestionEngine()
    
    # Check if Root Path exists
    if engine.root_path.exists():
        print(f"\nRoot Path Found: {engine.root_path}")
        print(f"Resolved Folders: {engine.folders}")

        # List files in 02_VOICE_GUIDES
        print("\n--- Listing Files in 02_VOICE_GUIDES ---")
        voice_guides = engine.list_voice_guides()
        if voice_guides:
             print(f"Found {len(voice_guides)} files:")
             for f in voice_guides:
                 print(f" - {f}")
        else:
             print("No files found in 02_VOICE_GUIDES (or folder missing).")

    else:
        print(f"\nRoot Path NOT FOUND: {engine.root_path}")
        print("Please ensure the external drive/cloud storage is mounted.")

if __name__ == "__main__":
    test_engine()
