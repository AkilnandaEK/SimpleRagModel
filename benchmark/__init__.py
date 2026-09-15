"""benchmark package — Week 7 Agent Loop vs Deterministic Workflow benchmark glue.

This package holds the benchmark configuration and LLM adapter. The agent,
workflow, tools, safety and telemetry live in their own top-level packages;
the benchmark evaluation lives under ``eval/``. Everything runs from the
Week 3 project root and reuses the shared ``app.services`` RAG pipeline.
"""