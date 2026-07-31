#!/usr/bin/env python
"""Wrapper script to perform incremental updates from OpenAlex.
The core logic is already implemented in fetch_openalex.py which 
reads 'last_updated' from the sync_meta table and performs an 
incremental fetch.
"""

from fetch_openalex import main

if __name__ == "__main__":
    print("Starting incremental OpenAlex update...")
    main()
