# Foundation and licensing

PatchProof is an isolated derivative of Eval Lab's local evaluation approach at
source commit `89fbe761cbdaa1bfa8c45749d5a89d1ee8e6149e`.

- `backend/patchproof/canonical.py` is copied unchanged from
  `src/llm_eval_lab/utils/json.py` (MIT, copyright 2026 Jaelucard).
- The supplied MIT LICENSE is preserved.
- FastAPI, React/TypeScript/Vite and SQLite retain the foundation's stack.
- PatchProof's support-ticket evaluator, fixed contract, stable test identity,
  partitioning, orchestrator, fixture adapter, provider gate, persistence and UI
  are purpose-specific. The generic Eval Lab case hash/comparison is untouched.
- No existing databases, secrets, environment files or Git metadata were copied.

Prompt identity and model/configuration identity are stored separately from
stable case integrity. PatchProof does not relax Eval Lab's generic pairing rule.
