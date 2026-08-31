import os

DUMMY_ROOT = "dummy_assets"
FOLDERS = [
    "01_VISUAL_REFERENCES",
    "02_VOICE_GUIDES",
    "03_METADATA_MASTER"
]

def create_dummy_structure():
    if not os.path.exists(DUMMY_ROOT):
        os.makedirs(DUMMY_ROOT)
    
    for folder in FOLDERS:
        path = os.path.join(DUMMY_ROOT, folder)
        if not os.path.exists(path):
            os.makedirs(path)
            print(f"Created: {path}")

    # Create Dummy Image
    with open(os.path.join(DUMMY_ROOT, "01_VISUAL_REFERENCES", "ref_image.jpg"), "w") as f:
        f.write("dummy image content")

    # Create Dummy Voice Guide
    with open(os.path.join(DUMMY_ROOT, "02_VOICE_GUIDES", "redCola_Guide.txt"), "w") as f:
        f.write("This is the voice guide for redCola.")

    # Create Dummy Master Metadata
    with open(os.path.join(DUMMY_ROOT, "03_METADATA_MASTER", "master_data.csv"), "w") as f:
        f.write("Title,Composer,Description,Keywords\nMaster Track 1,Comp A,Desc A,Key A")

    print("\nDummy Assets Created Successfully.")

if __name__ == "__main__":
    create_dummy_structure()
