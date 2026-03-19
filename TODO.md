# Deep C++17 Modernization & Langfuse Fix TODO

## Step 1: ✅ Create TODO.md

## Step 2: ✅ Edit core/ast_modernizer.py
- Added RAW_ARRAY, C_STRING, POSIX_FILE, MANUAL_INIT, INDEX_LOOP detectors.

## Step 3: [PENDING] Edit core/inspect_parser.py  
- _DEFAULT_TARGET_STD="c++17"; comment C++20+ rules; rename score_cpp23_compliance→score_cpp17_compliance.

## Step 4: [PENDING] Edit agents/function_modernizer.py
- Update import/call to score_cpp17_compliance.
- Prompt "DEEP C++17 rewrite" (unique_ptr/range-for/filesystem/constexpr mandatory).
- reflection_max_iters 2→4; similarity guards lower (0.88→0.75 etc.); min_score 20→10.

## Step 5: [PENDING] Edit agents/workflow.py
- System prompt emphasize "deep RAII ownership, mandatory range-for/unique_ptr".

## Step 6: [PENDING] Edit core/llm_shared.py
- Print exact missing env vars on Langfuse disable.

## Step 7: [PENDING] Create .env.example + docs/langfuse-setup.md
- LANGFUSE_* placeholders + setup steps.

## Step 8: [PENDING] Update cli.py/README.md
- Langfuse mention + --reflection-iters flag.

## Step 9: [PENDING] Test
- python cli.py modernize test.cpp --reflection-iters=4 → deep changes (unique_ptr/range-for).
- LANGFUSE_* set → langfuse.com traces.

## Step 10: [FINAL] Git blackboxai/ branch + PR

**Next: Step 3 (core/inspect_parser.py)**
