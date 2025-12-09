#!/usr/bin/env python3
"""
Patch V8 12.8.374 for View8 compatibility.
Adapts the original View8 patch for V8 12.8.
"""

import re

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
    
    insert_idx = None
    for i, line in enumerate(lines):
        if 'void SharedFunctionInfo::SharedFunctionInfoPrint' in line:
            brace_count = 0
            for j in range(i, min(i + 100, len(lines))):
                brace_count += lines[j].count('{') - lines[j].count('}')
                if j > i and brace_count == 0:
                    insert_idx = j
                    break
            break
    
    if insert_idx:
        # V8 12.8.374 API verified from source:
        # - HasBytecodeArray() -> bool (DECL_GETTER, no params)
        # - GetActiveBytecodeArray(IsolateForSandbox) -> Tagged<BytecodeArray>
        # - BytecodeArray::Disassemble(std::ostream&) -> void
        # - GetIsolateForSandbox(*this) is the correct way to get Isolate in V8 12.x
        new_code = '''  os << "\\nStart BytecodeArray\\n";
  if (HasBytecodeArray()) {
    GetActiveBytecodeArray(GetIsolateForSandbox(*this))->Disassemble(os);
  }
  os << "\\nEnd BytecodeArray\\n";
  os << std::flush;
'''
        lines.insert(insert_idx, new_code)
        with open(path, 'w') as f:
            f.writelines(lines)
        print(f"Patched {path}")
    else:
        print(f"WARNING: Could not find insertion point in {path}")

def patch_code_serializer():
    """Add print on deserialize"""
    path = 'src/snapshot/code-serializer.cc'
    with open(path, 'r') as f:
        content = f.read()
    
    correct_print = '''
  std::cout << "\\nStart SharedFunctionInfo\\n";
  result->SharedFunctionInfoPrint(std::cout);
  std::cout << "\\nEnd SharedFunctionInfo\\n";
  std::cout << std::flush;

  return scope.CloseAndEscape(result);'''
    
    content = content.replace('return scope.CloseAndEscape(result);', correct_print)
    
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
    """Add additional printing for arrays and SharedFunctionInfo in objects.cc
    
    V8 12.x uses Cast<T>() instead of T::cast() - we need to handle both syntaxes.
    These patches are optional - if the exact patterns don't match, we skip them
    since the core SharedFunctionInfo bytecode printing is the critical part.
    """
    path = 'src/objects/objects.cc'
    with open(path, 'r') as f:
        content = f.read()
    
    patched = False
    
    # V8 12.x uses Cast<FixedArray>(*this) syntax
    # Try V8 12.x syntax first
    old_fixed_array_v12 = 'case FIXED_ARRAY_TYPE:\n      os << "<FixedArray[" << Cast<FixedArray>(*this).length() << "]>";\n      break;'
    new_fixed_array_v12 = '''case FIXED_ARRAY_TYPE:
      os << "<FixedArray[" << Cast<FixedArray>(*this).length() << "]>";
      os << "\\nStart FixedArray\\n";
      Cast<FixedArray>(*this)->FixedArrayPrint(os);
      os << "\\nEnd FixedArray\\n";
      break;'''
    
    if old_fixed_array_v12 in content:
        content = content.replace(old_fixed_array_v12, new_fixed_array_v12)
        print(f"  Patched FIXED_ARRAY_TYPE case (V8 12.x syntax)")
        patched = True
    else:
        # Try legacy syntax
        old_fixed_array = 'case FIXED_ARRAY_TYPE:\n      os << "<FixedArray[" << FixedArray::cast(*this).length() << "]>";\n      break;'
        new_fixed_array = '''case FIXED_ARRAY_TYPE:
      os << "<FixedArray[" << FixedArray::cast(*this).length() << "]>";
      os << "\\nStart FixedArray\\n";
      FixedArray::cast(*this).FixedArrayPrint(os);
      os << "\\nEnd FixedArray\\n";
      break;'''
        if old_fixed_array in content:
            content = content.replace(old_fixed_array, new_fixed_array)
            print(f"  Patched FIXED_ARRAY_TYPE case (legacy syntax)")
            patched = True
    
    if not patched:
        print(f"  WARNING: Could not patch FIXED_ARRAY_TYPE - syntax may have changed")
    
    with open(path, 'w') as f:
        f.write(content)
    print(f"Patched {path} (optional patches)")


if __name__ == '__main__':
    print("Applying View8 patches for V8 12.8.374...")
    patch_objects_printer()
    patch_code_serializer()
    patch_deserializer()
    patch_string()
    patch_objects_cc()
    print("All patches applied successfully!")
