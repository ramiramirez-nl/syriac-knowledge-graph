#!/usr/bin/env python
import uvicorn
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    root_dir = Path(__file__).parent.parent
    os.chdir(root_dir)
    sys.path.insert(0, str(root_dir))
    print("Starting Syriac Studies Knowledge Graph API...")
    uvicorn.run("api.main:app", host="127.0.0.1", port=8000, reload=True)
