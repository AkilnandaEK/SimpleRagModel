/// Published Week 10 notes: the verdict conclusion and the recorded failure
/// experiment.
///
/// **This is documentation, not a result source.** The live Week 10 benchmark
/// now executes through `POST /api/benchmark/week10/race` and renders whatever
/// that run returns (see `week10_race_models.dart`). Nothing in this file may be
/// presented as the outcome of a live execution, and it deliberately holds no
/// live metric — no pass rates, token counts or multipliers — so there is never
/// a second, competing source of "the Week 10 result".
///
/// Two things legitimately live here because a live race cannot produce them:
///
/// * the **published verdict**, which is a conclusion drawn across the whole
///   Week 10 investigation rather than an output of any single race execution;
/// * the **failure experiment**, which is a separate injection run documented in
///   `failure_case.md` and is never executed by the live benchmark endpoint.
library;

import 'package:flutter/foundation.dart';

/// The published Week 10 verdict, transcribed from `verdict.md`.
@immutable
class Week10PublishedVerdict {
  const Week10PublishedVerdict({
    required this.decision,
    required this.headline,
    required this.reasons,
    required this.revisitCondition,
  });

  static const Week10PublishedVerdict week10 = Week10PublishedVerdict(
    decision: 'KILL',
    headline:
        '30% vs 30% pass rate, 10/10 case agreement, and 2.0x context '
        're-send overhead.',
    reasons: [
      'Pass rate is identical (30% vs 30%, 10/10 case agreement) and 0/7 '
          'positive cases passed on either arm, so the squad showed no accuracy '
          'benefit.',
      'A Context Re-Send Multiplier of 2.0x: 3,964 estimated context tokens '
          'against the Single Agent\'s 2,024 real provider tokens, with 3,674 of '
          'those (93%) going to a Code-Sample Worker that produced no code on '
          'any case.',
      'The one demonstrated advantage — safe failure handling — is unproven by '
          'the score, because the shared evaluator marked the total-failure run '
          'correct.',
    ],
    revisitCondition:
        'Revisit only with code-sample-specific cases this set cannot measure, '
        'and with the shared-evaluator limitation addressed.',
  );

  /// "KILL".
  final String decision;

  /// One-line reason, quoted from the published verdict.
  final String headline;

  /// Supporting bullets, quoted from the published verdict.
  final List<String> reasons;

  final String revisitCondition;
}

/// Tone for a step in the recorded failure timeline.
enum Week10StepTone { neutral, bad, good }

/// One step of the recorded `hard:01` failure run.
@immutable
class Week10RecordedFailureStep {
  const Week10RecordedFailureStep(this.label, this.detail, this.tone);

  final String label;
  final String detail;
  final Week10StepTone tone;
}

/// The recorded HTTP 500 failure-injection experiment, from `failure_case.md`.
///
/// Labeled "Recorded Failure Experiment" in the UI. The live benchmark endpoint
/// runs the *clean* baseline race (`failure_injection_enabled == false`) and
/// never performs this injection, so nothing here describes a live run.
@immutable
class Week10RecordedFailureExperiment {
  const Week10RecordedFailureExperiment();

  static const Week10RecordedFailureExperiment week10 =
      Week10RecordedFailureExperiment();

  String get caseId => 'hard:01';

  String get summary =>
      'HTTP 500 injected into the Version/Deprecation Worker on hard:01.';

  String get outcome =>
      'No retry attempted. The run degraded gracefully: the orchestrator '
      'returned a safe refusal and the shared evaluator scored it correct.';

  /// The documented shared-evaluator limitation that makes the above unproven.
  String get evaluatorLimitation =>
      'Shared evaluator limitation — the safe refusal contained the generic '
      'token "version", so it matched the reference answer and was scored '
      'correct. The failure run must NOT be read as evidence that the '
      'Multi-Agent architecture handles errors well.';

  List<Week10RecordedFailureStep> get steps => const [
    Week10RecordedFailureStep(
      'Injected fault',
      'HTTP 500 raised inside the Version/Deprecation Worker.',
      Week10StepTone.bad,
    ),
    Week10RecordedFailureStep(
      'Retry attempted',
      'No — no retry logic exists or was added.',
      Week10StepTone.bad,
    ),
    Week10RecordedFailureStep(
      'Graceful degradation',
      'The orchestrator completed the run with a safe refusal instead of '
          'hallucinating an answer.',
      Week10StepTone.good,
    ),
    Week10RecordedFailureStep(
      'Code-Sample Worker still delegated',
      'Yes — the remaining worker was still called.',
      Week10StepTone.neutral,
    ),
    Week10RecordedFailureStep(
      'Hallucination / fabrication',
      'No fabricated output was produced.',
      Week10StepTone.good,
    ),
  ];
}
