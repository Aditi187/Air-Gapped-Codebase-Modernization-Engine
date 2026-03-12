from core.parser import extract_functions_from_cpp_file

# prepare smoke test
code = """
int add(int a, int b) { return a + b; }
void greet() { return; }
"""
with open('smoke_test.cpp','w') as f:
    f.write(code)

funcs = extract_functions_from_cpp_file('smoke_test.cpp')
print('functions count', len(funcs))
for i, f in enumerate(funcs, start=1):
    print('--- function', i)
    for k,v in f.items():
        print(f'{k}: {v!r}')
    print()

# cleanup
import os
os.remove('smoke_test.cpp')
