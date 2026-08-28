# Legacy Streamlit boundary

The reference implementation remains at the repository root:

- entry point: `../../app.py`
- dependencies: `../../requirements.txt`
- analytical modules: `../../modules/`

This directory deliberately contains no adapter code, imports, or symlinks. Phase 1 preserves
the legacy runtime untouched and treats it as the parity oracle for later vertical slices.

The pre-existing `../../api/` directory is also retained as a legacy prototype. New API work
lives in `../api/` and must not import its `sys.path`-based implementation.
