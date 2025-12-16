#!/usr/bin/env python3
import json
import sys
import os

def load_fle_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def extract_bytes_from_section(section_lines):
    """
    Parse a list of strings from an FLE section.
    Keep only lines starting with '🔢:'.
    Convert hex strings to bytes.
    Return a list of byte sequences (chunks).
    Note: In FLE file, relocation placeholders might separate chunks.
    """
    chunks = []
    current_chunk = bytearray()
    
    for line in section_lines:
        line = line.strip()
        if line.startswith("🔢:"):
            # Format: "🔢: 55 48 ..."
            hex_str = line.split(":", 1)[1].strip()
            # Remove spaces
            hex_str = hex_str.replace(" ", "")
            if hex_str:
                try:
                    data = bytes.fromhex(hex_str)
                    current_chunk.extend(data)
                except ValueError:
                    continue
        else:
            # If line is NOT machine code (e.g. relocation symbol, label),
            # it effectively breaks the continuity of the byte stream in file view.
            # So we finish the current chunk and start a new one.
            if current_chunk:
                chunks.append(bytes(current_chunk))
                current_chunk = bytearray()
    
    if current_chunk:
        chunks.append(bytes(current_chunk))
        
    return chunks

def extract_text_chunks(fle_obj):
    # Retrieve the list of lines for .text
    lines = []
    if "sections" in fle_obj and ".text" in fle_obj["sections"]:
        lines = fle_obj["sections"][".text"]["data"]
    elif ".text" in fle_obj:
        lines = fle_obj[".text"]
    
    return extract_bytes_from_section(lines)

def judge():
    try:
        input_data = json.load(sys.stdin)
        test_dir = input_data["test_dir"]
        build_dir = os.path.join(test_dir, "build")
        
        program_path = os.path.join(build_dir, "program")
        unused_fle_path = os.path.join(build_dir, "unused.fle")
        used_fle_path = os.path.join(build_dir, "used.fle")
        
        try:
            program_fle = load_fle_json(program_path)
            unused_fle = load_fle_json(unused_fle_path)
            used_fle = load_fle_json(used_fle_path)
        except Exception as e:
             print(json.dumps({"success": False, "message": f"Failed to load FLE files: {str(e)}"}))
             return

        # Program is an executable, so '🔢' lines are continuous (relocations applied)
        # But our extractor splits on non-🔢 lines (like labels).
        # Labels '📤:' still exist in program output?
        # Yes, from cat output we saw strings. But executable might not have labels?
        # Actually in Task 8 ld.cpp, we see:
        # result.sections[name].data is vector<uint8_t>.
        # FLEWriter writes it.
        # If it's pure binary data, FLEWriter might dump it as a single (or multiple) 🔢 lines.
        # It likely WON'T have labels or ❓ lines if symbols are stripped or resolved.
        # So for 'program', we simply concatenate all chunks into one big binary blob.
        
        program_chunks = extract_text_chunks(program_fle)
        program_bin = b"".join(program_chunks)
        
        unused_chunks = extract_text_chunks(unused_fle)
        used_chunks = extract_text_chunks(used_fle)
        
        # Helper to check if ANY significant chunk is present
        # We define significant as > 4 bytes to avoid matching common prologue/epilogue only
        # Prologue: 55 48 89 e5 (4 bytes)
        # Epilogue: 5d c3 (2 bytes) or c3 (1 byte)
        
        def is_present(target_chunks, container_bin):
            for chunk in target_chunks:
                # Remove common prologue (push rbp; mov rbp, rsp)
                if chunk.startswith(b'\x55\x48\x89\xe5'):
                    chunk = chunk[4:]
                
                # If remaining chunk is too small, skip it (too risky for false positive)
                if len(chunk) < 2: 
                    continue
                    
                if chunk in container_bin:
                    return True
            return False

        # Verification 1: 'used.o' MUST be present
        # used.c: return 10. Code: b8 0a ... c3.
        # This is significant enough.
        if not is_present(used_chunks, program_bin):
             print(json.dumps({"success": False, "message": "Verification Failed: 'used.o' code not detected in program!"}))
             return

        # Verification 2: 'unused.o' MUST NOT be present
        if is_present(unused_chunks, program_bin):
            print(json.dumps({"success": False, "message": "Verification Failed: 'unused.o' code WAS detected in program!"}))
            return

        print(json.dumps({"success": True, "message": "Selective linking verified."}))
        
    except Exception as e:
        print(json.dumps({"success": False, "message": f"Judge error: {str(e)}"}))

if __name__ == "__main__":
    judge()
