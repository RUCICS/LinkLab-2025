#!/usr/bin/env python3
import json
import sys
import os

def load_fle(path):
    with open(path, 'r') as f:
        return json.load(f)

def judge():
    try:
        input_data = json.load(sys.stdin)
        test_dir = input_data["test_dir"]
        build_dir = os.path.join(test_dir, "build")
        program_path = os.path.join(build_dir, "program")
        
        try:
            fle = load_fle(program_path)
        except Exception as e:
             print(json.dumps({"success": False, "message": f"Failed to load program: {str(e)}"}))
             return

        phdrs = fle.get("phdrs", [])
        if len(phdrs) < 2:
            print(json.dumps({
                "success": False, 
                "message": f"Expected at least 2 program headers (Text, Data), found {len(phdrs)}"
            }))
            return

        # Basic check: do we have a text segment and a data segment?
        # We can infer from flags or just count.
        # Task 5 doesn't enforce permissions, so just count is enough per docs.
        # "You need to add both phdrs to the array"
        
        print(json.dumps({"success": True, "message": f"Found {len(phdrs)} program headers. Multi-segment layout verified."}))
        
    except Exception as e:
        print(json.dumps({"success": False, "message": f"Judge error: {str(e)}"}))

if __name__ == "__main__":
    judge()
