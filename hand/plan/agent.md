# hand-planner

Hand's planning brain. Plans sequences of GUI operations; never executes them.

- **Tools:** none beyond message output (steps are parsed from JSON text).
- **Model:** default or `-m provider/model` (e.g. high-reasoning variant).
- **Session:** resume with `-s` so cross-call context persists.
- **System prompt:** injected from `hand/plan/prompts.py`.
