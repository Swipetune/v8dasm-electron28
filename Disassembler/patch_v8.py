#!/usr/bin/env python3
"""
Patch V8 12.8.374 for View8 compatibility.
Adapts the original View8 patch for V8 12.8.

KEY INSIGHT: Nested functions are stored in FixedArray constant pools.
We must recursively print FixedArray contents to see all SharedFunctionInfo.
"""

import re
import os

def patch_objects_printer():
    """Add BytecodeArray disassembly to SharedFunctionInfoPrint"""
    path = 'src/diagnostics/objects-printer.cc'
    with open(path, 'r') as f:
        lines = f.readlines()
    
    # Comment out PrintSourceCode if present
    for i, line in enumerate(lines):
        if 'PrintSourceCode(os);' in line and '//' not in line:
            lines[i] = '  // ' + line.lstrip()
            print(f"  Commented out PrintSourceCode at line {i+1}")
    
    # View8: We DO NOT inject Disassemble() here anymore because:
    # 1. V8 12.x requires GetIsolateForSandbox(*this)
    # 2. objects-printer.cc lacks the context/headers to resolve this
    # 3. The recursive printer in code-serializer.cc handles extraction safely
    print(f"  Skipped injecting Disassemble() into objects-printer.cc (unsafe context)")

    with open(path, 'w') as f:
        f.writelines(lines)
    print(f"Patched {path} (commented out source print only)")

def patch_code_serializer():
    """Add comprehensive print on deserialize - iterates constant pool for nested functions"""
    path = 'src/snapshot/code-serializer.cc'
    with open(path, 'r') as f:
        content = f.read()
    
    # Add include for iostream if not present
    if '#include <iostream>' not in content:
        content = '#include <iostream>\n' + content
        print(f"  Added iostream include")
    
    # Add recursive function printer before the Deserialize function
    # This will iterate through constant pools to find all nested SharedFunctionInfo
    # V8 12.8.374 API verified from chromium.googlesource.com:
    # - BytecodeArray::constant_pool() returns Tagged<TrustedFixedArray>
    # - TrustedFixedArray::get(i) returns Tagged<Object>
    # - IsSharedFunctionInfo(obj) checks type
    # - Cast<SharedFunctionInfo>(obj) casts to SFI
    recursive_printer = '''
// View8: Recursive function to print all nested SharedFunctionInfo
// V8 12.8.374 API - uses TrustedFixedArray for constant pool
#include <set>

static std::set<Address> printed_sfis;  // Track already-printed SFIs to avoid infinite recursion

static void PrintAllSharedFunctionInfos(Isolate* isolate, Tagged<SharedFunctionInfo> sfi, std::ostream& os, int depth = 0) {
  // Avoid infinite recursion by tracking printed SFIs
  Address sfi_addr = sfi.ptr();
  if (printed_sfis.count(sfi_addr) > 0) {
    return;
  }
  printed_sfis.insert(sfi_addr);
  
  std::string indent(depth * 2, ' ');
  os << "\\n" << indent << "; ====== SharedFunctionInfo (depth " << depth << ") ======\\n";
  
  // Print function name if available
  if (sfi->HasSharedName()) {
    os << indent << "; Name: ";
    ShortPrint(sfi->Name(), os);
    os << "\\n";
  }
  
  // Print bytecode if available
  if (sfi->HasBytecodeArray()) {
    Tagged<BytecodeArray> bytecode = sfi->GetBytecodeArray(isolate);
    os << indent << "; Bytecode length: " << bytecode->length() << "\\n";
    
    // Disassemble the bytecode
    os << indent << "; --- Bytecode Disassembly ---\\n";
    bytecode->Disassemble(os);
    os << std::flush;
    
    // Get constant pool and iterate for nested functions
    Tagged<TrustedFixedArray> constant_pool = bytecode->constant_pool();
    int pool_length = constant_pool->length();
    
    os << indent << "; Constant pool size: " << pool_length << "\\n";
    
    // Iterate through constant pool looking for nested SharedFunctionInfo
    for (int i = 0; i < pool_length; i++) {
      Tagged<Object> entry = constant_pool->get(i);
      if (IsSharedFunctionInfo(entry)) {
        os << indent << "; Found nested function at constant pool index " << i << "\\n";
        PrintAllSharedFunctionInfos(isolate, Cast<SharedFunctionInfo>(entry), os, depth + 1);
      }
    }
  } else {
    os << indent << "; (No bytecode - may be native or uncompiled)\\n";
  }
  
  os << indent << "; ====== End SharedFunctionInfo (depth " << depth << ") ======\\n";
}

'''    
    # Insert before CodeSerializer::Deserialize function
    deserialize_pattern = r'(MaybeDirectHandle<SharedFunctionInfo>\s+CodeSerializer::Deserialize\s*\()'
    if re.search(deserialize_pattern, content):
        content = re.sub(deserialize_pattern, recursive_printer + r'\1', content, count=1)
        print(f"  Added recursive SharedFunctionInfo printer")
    
    # Replace the return statement to call our recursive printer
    old_return = 'return scope.CloseAndEscape(result);'
    new_return = '''// View8: Clear tracking set and print all functions
  printed_sfis.clear();
  std::cout << "\\n; ===== V8DASM VIEW8: Starting Full Bytecode Extraction =====\\n";
  std::cout << "; V8 Version: 12.8.374\\n";
  std::cout << "; Recursively extracting all SharedFunctionInfo from constant pools...\\n";
  PrintAllSharedFunctionInfos(isolate, *result, std::cout, 0);
  std::cout << "\\n; ===== V8DASM VIEW8: Extraction Complete =====\\n";
  std::cout << "; Total functions extracted: " << printed_sfis.size() << "\\n";
  std::cout << std::flush;

  return scope.CloseAndEscape(result);'''
    
    if old_return in content:
        content = content.replace(old_return, new_return, 1)  # Only replace first occurrence
        print(f"  Replaced return statement with recursive printer call")
    else:
        print(f"  WARNING: Could not find return statement to replace")
    
    with open(path, 'w') as f:
        f.write(content)
    print(f"Patched {path}")

def patch_deserializer():
    """Remove magic number check"""
    path = 'src/snapshot/deserializer.cc'
    with open(path, 'r') as f:
        content = f.read()
    
    content = content.replace(
        'CHECK_EQ(magic_number_, SerializedData::kMagicNumber);',
        '// CHECK_EQ(magic_number_, SerializedData::kMagicNumber); // Disabled for View8'
    )
    
    with open(path, 'w') as f:
        f.write(content)
    print(f"Patched {path}")

def patch_string():
    """Remove string truncation - V8 12.8 compatible
    
    Only patches the specific truncation block in StringPrint function.
    Looks for the pattern:
      if (length() > kMaxShortPrintLength) {
        os << "<String...>";
        return;
      }
    And comments it out without touching other code.
    """
    path = 'src/objects/string.cc'
    with open(path, 'r') as f:
        content = f.read()
    
    # V8 12.x pattern for string truncation in StringPrint
    # This is more precise than line-by-line patching
    import re
    
    # Pattern 1: Direct length check truncation
    pattern1 = r'if\s*\(\s*length\(\)\s*>\s*kMaxShortPrintLength\s*\)\s*\{[^}]*os\s*<<[^}]*String[^}]*return;[^}]*\}'
    
    # Pattern 2: Alternative truncation pattern
    pattern2 = r'if\s*\([^)]*kMaxShortPrintLength[^)]*\)\s*\{[^}]*return;[^}]*\}'
    
    replaced = False
    for pattern in [pattern1, pattern2]:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            original = match.group(0)
            commented = '/* View8 patch: truncation disabled\n' + original + '\n*/'
            content = content.replace(original, commented)
            print(f"  Patched truncation block in {path}")
            replaced = True
            break
    
    if not replaced:
        # Fallback: Just increase the limit instead of removing
        content = content.replace(
            'kMaxShortPrintLength = 1024',
            'kMaxShortPrintLength = 1024 * 1024  // View8: increased limit'
        )
        content = content.replace(
            'kMaxShortPrintLength = 80',
            'kMaxShortPrintLength = 1024 * 1024  // View8: increased limit'
        )
        print(f"  Fallback: increased kMaxShortPrintLength limit")
    
    with open(path, 'w') as f:
        f.write(content)
    print(f"Patched {path}")

def patch_objects_cc():
    """Add additional printing for arrays in objects.cc using REGEX patterns
    
    V8 12.x uses Cast<T>() instead of T::cast().
    Use regex to be more flexible with whitespace and formatting.
    """
    path = 'src/objects/objects.cc'
    
    if not os.path.exists(path):
        print(f"  WARNING: {path} not found, skipping objects.cc patches")
        return
        
    with open(path, 'r') as f:
        content = f.read()
    
    patched = False
    
    # Use regex to match FIXED_ARRAY_TYPE case with flexible whitespace
    # Pattern matches: case FIXED_ARRAY_TYPE: ... break;
    fixed_array_pattern = r'(case\s+FIXED_ARRAY_TYPE\s*:\s*\n\s*)(os\s*<<\s*"<FixedArray\["[^;]+;)(\s*\n\s*break;)'
    
    fixed_array_replacement = r'''\1\2
      // View8: Print FixedArray contents for nested function discovery
      {
        auto arr = Cast<FixedArray>(*this);
        int len = arr->length();
        if (len > 0 && len < 1000) {  // Limit to avoid huge arrays
          os << "\n; #region FixedArray Contents\n";
          arr->FixedArrayPrint(os);
          os << "; #endregion\n";
        }
      }\3'''
    
    new_content, count = re.subn(fixed_array_pattern, fixed_array_replacement, content)
    if count > 0:
        content = new_content
        print(f"  Patched FIXED_ARRAY_TYPE case (regex match)")
        patched = True
    else:
        # Fallback: Try to find and inject after FIXED_ARRAY_TYPE case
        if 'case FIXED_ARRAY_TYPE:' in content:
            # Find the case and inject code after the os << line
            lines = content.split('\n')
            new_lines = []
            in_fixed_array_case = False
            injected = False
            
            for i, line in enumerate(lines):
                new_lines.append(line)
                if 'case FIXED_ARRAY_TYPE:' in line:
                    in_fixed_array_case = True
                elif in_fixed_array_case and not injected:
                    if 'os <<' in line and 'FixedArray' in line:
                        # Inject after this line
                        inject_code = '''      // View8: Print FixedArray contents
      {
        auto arr = Cast<FixedArray>(*this);
        if (arr->length() > 0 && arr->length() < 500) {
          os << "\\n; FixedArray contents:\\n";
          arr->FixedArrayPrint(os);
        }
      }'''
                        new_lines.append(inject_code)
                        injected = True
                        in_fixed_array_case = False
                        print(f"  Injected FixedArray printing code (fallback)")
                        patched = True
            
            content = '\n'.join(new_lines)
    
    if not patched:
        print(f"  INFO: FIXED_ARRAY_TYPE patch skipped - will rely on recursive printer in code-serializer.cc")
    
    with open(path, 'w') as f:
        f.write(content)
    print(f"Patched {path}")


if __name__ == '__main__':
    print("Applying View8 patches for V8 12.8.374...")
    patch_objects_printer()
    patch_code_serializer()
    patch_deserializer()
    patch_string()
    patch_objects_cc()
    print("All patches applied successfully!")
