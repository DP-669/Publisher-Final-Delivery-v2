from engine import IngestionEngine
from prompts import PromptEngine
import pandas as pd
import os

def test_asset_generation():
    print("Testing Asset Generation Logic...")
    
    # 1. Setup Engine and Fake Data
    engine = IngestionEngine()
    
    # Dummy Meta
    data = {
        'Title': ['Test Track 1', 'Test Track 2'],
        'Composer': ['Composer A', 'Composer B'],
        'Description': ['Epic orchestral build', 'Quiet piano intro'],
        'Keywords': ['Action, Drama', 'Sad, Emotional']
    }
    df = pd.DataFrame(data)
    
    # 2. Test Prompt Construction
    prompt_engine = PromptEngine()
    catalog = "SSC"
    prompt = prompt_engine.construct_asset_prompt(df, catalog)
    print(f"\n[Constructed Prompt Preview]\n{prompt[:200]}...")
    
    # 3. Test Blueprint Retrieval
    blueprint = engine.get_voice_guide(catalog)
    if blueprint:
        print(f"\n[Blueprint Retrieved] Length: {len(blueprint)} chars")
    else:
        print("\n[Warning] Blueprint not found (check local path).")
        # Create a dummy blueprint if missing for testing logic flow
        if engine.folders["02_VOICE_GUIDES"]:
             dummy_bp = engine.folders["02_VOICE_GUIDES"] / "SSC_Voice_Guide.txt"
             if not dummy_bp.exists():
                 with open(dummy_bp, "w") as f:
                     f.write("System Instruction: Write like a cool person.")
                 print("Created dummy blueprint for testing.")
                 blueprint = "System Instruction: Write like a cool person."

    # 4. Mock API Call (We won't make a real call without a key, but we check the method existence)
    print("\n[API Integration Check]")
    if hasattr(engine, 'generate_marketing_assets'):
        print("generate_marketing_assets method exists.")
    else:
        print("generate_marketing_assets method MISSING.")

if __name__ == "__main__":
    test_asset_generation()
