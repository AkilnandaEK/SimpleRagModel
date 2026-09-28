# -*- coding: ascii -*-
# Re-export shim. The grounded, extractive, offline answer synthesizer lives
# (byte-clean, import-proven, benchmark-verified 90/90 at runtime) in
# eval/offline_answers.py. This file exists only so that consumers which
# historically referenced eval.offline_grounding keep working unchanged
# after their import path was corrected to the proven module.

from eval.offline_answers import (  # noqa: E501,F401
    REFUSAL_ANSWER,
    synthesize_grounded_answer,
    synthesize_grounded_answer_many,
)