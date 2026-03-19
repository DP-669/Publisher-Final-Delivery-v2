from prompts import PromptEngine
from engine import IngestionEngine
import pandas as pd
import os

def test_ui_logic():
    print("Testing UI Logic & Prompts...")
    
    # Test Prompt Engine
    prompts = PromptEngine()
    
    # Test Description Prompt
    title = "Epic Adventure"
    desc = "A big orchestral track."
    catalog = "SSC"
    
    p1 = prompts.generate_description_prompt(title, desc, catalog)
    print(f"\n[Description Prompt Generated] (Catalog: {catalog})\n{p1}")
    
    # Test Engine Integration check
    engine = IngestionEngine()
    print(f"\nEngine initialized with path: {engine.root_path}")
    
    if engine.folders["03_METADATA_MASTER"]:
        print("Engine successfully resolved folders.")
        
        # Test Metadata Filtering
        print("\nTesting Metadata Filtering for 'redCola':")
        # Create a dummy redCola csv if not exists for testing
        dummy_csv = engine.folders["03_METADATA_MASTER"] / "redCola_Master.csv"
        if not dummy_csv.exists():
            with open(dummy_csv, "w") as f:
                f.write("Title,Composer,Description,Keywords\nTest Track,Test Comp,Desc,Keys")
            print("Created dummy redCola_Master.csv")
            
        df = engine.get_metadata_df(catalog="redCola")
        if df is not None:
            print(f"Successfully retrieved metadata for redCola. Rows: {len(df)}")
        else:
            print("Failed to retrieve metadata for redCola.")
            
    else:
        print("Engine running, but folders not resolved (check path).")

if __name__ == "__main__":
    test_ui_logic()
