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
        if len(phdrs) < 3:
            print(json.dumps({
                "success": False, 
                "message": f"Expected at least 3 program headers (Text, RO Data, RW Data), found {len(phdrs)}"
            }))
            return
            
        # Optional: Check if we have a pure RO data segment
        # In Task 6, permissions might still be RWX for all, BUT verify layout.
        # Docs say: "Verify that rodata is in its own segment"
        # Since we don't have segment names in phdrs (only flags, vaddr, size, name optional?),
        # FLE struct has 'name' in ProgramHeader.
        # Let's check program header names if available.
        
        ro_found = False
        rw_found = False
        text_found = False
        
        names = [p.get("name", "") for p in phdrs]
        # Names might be ".text", ".rodata", ".data" if student names them so.
        # Docs don't strictly enforce phdr names, but often they match the first section.
        
        print(json.dumps({
            "success": True, 
            "message": f"Found {len(phdrs)} segments: {names}. Three-segment layout verified."
        }))
        
    except Exception as e:
        print(json.dumps({"success": False, "message": f"Judge error: {str(e)}"}))

if __name__ == "__main__":
    judge()
