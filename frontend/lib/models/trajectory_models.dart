/// Typed models for the Week 8 trajectory evaluation API response
/// (POST /api/trajectory/run).
///
/// Every number here is computed by the backend metrics engine. The UI renders
/// them and derives nothing — in particular it never recomputes the gap, the
/// pass rates or the mitigation deltas, so the tab and the CLI report can never
/// disagree.
library;

double _d(Object? v) => (v as num?)?.toDouble() ?? 0.0;
int _i(Object? v) => (v as num?)?.toInt() ?? 0;
List<String> _strings(Object? v) =>
    (v as List?)?.map((e) => e.toString()).toList() ?? const [];

/// The four telemetry dimensions plus cost/latency distribution for one run.
class TrajectoryMetrics {
  final String label;
  final int totalCases;
  final double toolChoiceAccuracy;
  final double argumentValidityRate;
  final double stepEfficiency;
  final double stepsRatio;
  final int totalSteps;
  final int totalOptimalSteps;
  final int controlSteps;
  final int erroredCases;
  final int scoredCases;

  final double costP50Usd;
  final double costMaxUsd;
  final double costTotalUsd;
  final String costMaxCaseId;

  final double latencyP50Ms;
  final double latencyP99Ms;
  final double latencyMaxMs;
  final double tokensP50;
  final int tokensMax;
  final int tokensTotal;

  final double outcomePassRate;
  final double trajectoryPassRate;
  final double gap;
  final Map<String, int> failureModeCounts;

  const TrajectoryMetrics({
    required this.label,
    required this.totalCases,
    required this.toolChoiceAccuracy,
    required this.argumentValidityRate,
    required this.stepEfficiency,
    required this.stepsRatio,
    required this.totalSteps,
    required this.totalOptimalSteps,
    required this.controlSteps,
    required this.erroredCases,
    required this.scoredCases,
    required this.costP50Usd,
    required this.costMaxUsd,
    required this.costTotalUsd,
    required this.costMaxCaseId,
    required this.latencyP50Ms,
    required this.latencyP99Ms,
    required this.latencyMaxMs,
    required this.tokensP50,
    required this.tokensMax,
    required this.tokensTotal,
    required this.outcomePassRate,
    required this.trajectoryPassRate,
    required this.gap,
    required this.failureModeCounts,
  });

  factory TrajectoryMetrics.fromJson(Map<String, dynamic> json) {
    final rawCounts = json['failure_mode_counts'] as Map<String, dynamic>? ?? {};
    return TrajectoryMetrics(
      label: json['label'] as String? ?? '',
      totalCases: _i(json['total_cases']),
      toolChoiceAccuracy: _d(json['tool_choice_accuracy']),
      argumentValidityRate: _d(json['argument_validity_rate']),
      stepEfficiency: _d(json['step_efficiency']),
      stepsRatio: _d(json['steps_ratio']),
      totalSteps: _i(json['total_steps']),
      totalOptimalSteps: _i(json['total_optimal_steps']),
      controlSteps: _i(json['control_steps']),
      erroredCases: _i(json['errored_cases']),
      scoredCases: _i(json['scored_cases']),
      costP50Usd: _d(json['cost_p50_usd']),
      costMaxUsd: _d(json['cost_max_usd']),
      costTotalUsd: _d(json['cost_total_usd']),
      costMaxCaseId: json['cost_max_case_id'] as String? ?? '',
      latencyP50Ms: _d(json['latency_p50_ms']),
      latencyP99Ms: _d(json['latency_p99_ms']),
      latencyMaxMs: _d(json['latency_max_ms']),
      tokensP50: _d(json['tokens_p50']),
      tokensMax: _i(json['tokens_max']),
      tokensTotal: _i(json['tokens_total']),
      outcomePassRate: _d(json['outcome_pass_rate']),
      trajectoryPassRate: _d(json['trajectory_pass_rate']),
      gap: _d(json['gap']),
      failureModeCounts: rawCounts.map((k, v) => MapEntry(k, _i(v))),
    );
  }
}

/// One scored step inside a trajectory.
class TrajectoryStep {
  final int step;
  final String tool;
  final bool toolChoiceOk;
  final String toolChoiceReason;
  final bool argsOk;
  final String argsReason;
  final Map<String, dynamic>? toolInput;
  final String observation;

  const TrajectoryStep({
    required this.step,
    required this.tool,
    required this.toolChoiceOk,
    required this.toolChoiceReason,
    required this.argsOk,
    required this.argsReason,
    required this.toolInput,
    required this.observation,
  });

  factory TrajectoryStep.fromJson(Map<String, dynamic> json) => TrajectoryStep(
    step: _i(json['step']),
    tool: json['tool'] as String? ?? '',
    toolChoiceOk: json['tool_choice_ok'] as bool? ?? false,
    toolChoiceReason: json['tool_choice_reason'] as String? ?? '',
    argsOk: json['args_ok'] as bool? ?? true,
    argsReason: json['args_reason'] as String? ?? '',
    toolInput: json['tool_input'] as Map<String, dynamic>?,
    observation: json['observation'] as String? ?? '',
  );
}

/// One query's combined outcome + trajectory verdict.
class TrajectoryCaseResult {
  final String caseId;
  final String scenarioKey;
  final String question;
  final List<String> actualPath;
  final bool trajectoryPass;
  final String pathReason;
  final String failureReason;
  final bool outcomePass;
  final String outcomeMatchType;
  final bool isFalsePositive;
  final double toolChoiceAccuracy;
  final double argumentValidityRate;
  final double stepEfficiency;
  final int actualSteps;
  final int optimalSteps;
  final double costUsd;
  final double latencyMs;
  final int totalTokens;
  final List<String> failureModes;
  final String answer;
  final String? infraError;
  final List<TrajectoryStep> steps;

  const TrajectoryCaseResult({
    required this.caseId,
    required this.scenarioKey,
    required this.question,
    required this.actualPath,
    required this.trajectoryPass,
    required this.pathReason,
    required this.failureReason,
    required this.outcomePass,
    required this.outcomeMatchType,
    required this.isFalsePositive,
    required this.toolChoiceAccuracy,
    required this.argumentValidityRate,
    required this.stepEfficiency,
    required this.actualSteps,
    required this.optimalSteps,
    required this.costUsd,
    required this.latencyMs,
    required this.totalTokens,
    required this.failureModes,
    required this.answer,
    required this.infraError,
    required this.steps,
  });

  factory TrajectoryCaseResult.fromJson(Map<String, dynamic> json) =>
      TrajectoryCaseResult(
        caseId: json['case_id'] as String? ?? '',
        scenarioKey: json['scenario_key'] as String? ?? '',
        question: json['question'] as String? ?? '',
        actualPath: _strings(json['actual_path']),
        trajectoryPass: json['trajectory_pass'] as bool? ?? false,
        pathReason: json['path_reason'] as String? ?? '',
        failureReason: json['failure_reason'] as String? ?? '',
        outcomePass: json['outcome_pass'] as bool? ?? false,
        outcomeMatchType: json['outcome_match_type'] as String? ?? '',
        isFalsePositive: json['is_false_positive'] as bool? ?? false,
        toolChoiceAccuracy: _d(json['tool_choice_accuracy']),
        argumentValidityRate: _d(json['argument_validity_rate']),
        stepEfficiency: _d(json['step_efficiency']),
        actualSteps: _i(json['actual_steps']),
        optimalSteps: _i(json['optimal_steps']),
        costUsd: _d(json['cost_usd']),
        latencyMs: _d(json['latency_ms']),
        totalTokens: _i(json['total_tokens']),
        failureModes: _strings(json['failure_modes']),
        answer: json['answer'] as String? ?? '',
        infraError: json['infra_error'] as String?,
        steps: ((json['steps'] as List?) ?? [])
            .map((e) => TrajectoryStep.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
}

/// One row of the per-mode regression matrix.
class ModeDelta {
  final String code;
  final String name;
  final int before;
  final int after;
  final int delta;
  final String status; // IMPROVED | WORSENED | NEW | UNCHANGED

  const ModeDelta({
    required this.code,
    required this.name,
    required this.before,
    required this.after,
    required this.delta,
    required this.status,
  });

  factory ModeDelta.fromJson(Map<String, dynamic> json) => ModeDelta(
    code: json['code'] as String? ?? '',
    name: json['name'] as String? ?? '',
    before: _i(json['before']),
    after: _i(json['after']),
    delta: _i(json['delta']),
    status: json['status'] as String? ?? 'UNCHANGED',
  );
}

/// The single mitigation experiment and its measured price.
class MitigationResult {
  final String name;
  final String description;
  final String targetMode;
  final String targetModeName;
  final int targetBefore;
  final int targetAfter;
  final int targetDelta;
  final bool wasTopMode;
  final String measuredTopMode;
  final int interventions;

  final double latencyP50DeltaMs;
  final double latencyP99DeltaMs;
  final double tokensPerQueryDelta;
  final double costPerQueryDeltaUsd;
  final double costP50DeltaUsd;
  final int stepsDelta;

  const MitigationResult({
    required this.name,
    required this.description,
    required this.targetMode,
    required this.targetModeName,
    required this.targetBefore,
    required this.targetAfter,
    required this.targetDelta,
    required this.wasTopMode,
    required this.measuredTopMode,
    required this.interventions,
    required this.latencyP50DeltaMs,
    required this.latencyP99DeltaMs,
    required this.tokensPerQueryDelta,
    required this.costPerQueryDeltaUsd,
    required this.costP50DeltaUsd,
    required this.stepsDelta,
  });

  factory MitigationResult.fromJson(Map<String, dynamic> json) {
    final price = json['price'] as Map<String, dynamic>? ?? {};
    return MitigationResult(
      name: json['name'] as String? ?? '',
      description: json['description'] as String? ?? '',
      targetMode: json['target_mode'] as String? ?? '',
      targetModeName: json['target_mode_name'] as String? ?? '',
      targetBefore: _i(json['target_before']),
      targetAfter: _i(json['target_after']),
      targetDelta: _i(json['target_delta']),
      wasTopMode: json['was_top_mode'] as bool? ?? false,
      measuredTopMode: json['measured_top_mode'] as String? ?? '',
      interventions: _i(json['interventions']),
      latencyP50DeltaMs: _d(price['latency_p50_delta_ms']),
      latencyP99DeltaMs: _d(price['latency_p99_delta_ms']),
      tokensPerQueryDelta: _d(price['tokens_per_query_delta']),
      costPerQueryDeltaUsd: _d(price['cost_per_query_delta_usd']),
      costP50DeltaUsd: _d(price['cost_p50_delta_usd']),
      stepsDelta: _i(price['steps_delta']),
    );
  }
}

/// One attack attempt in the prompt-injection bonus suite.
class AttackOutcome {
  final String payloadId;
  final String label;
  final bool attackSucceeded;
  final bool guardrailBlocked;
  final List<String> guardrailViolations;
  final List<String> markersHit;
  final String answerExcerpt;
  final bool conclusive;
  final bool becameRefusal;

  const AttackOutcome({
    required this.payloadId,
    required this.label,
    required this.attackSucceeded,
    required this.guardrailBlocked,
    required this.guardrailViolations,
    required this.markersHit,
    required this.answerExcerpt,
    required this.conclusive,
    required this.becameRefusal,
  });

  factory AttackOutcome.fromJson(Map<String, dynamic> json) => AttackOutcome(
    payloadId: json['payload_id'] as String? ?? '',
    label: json['label'] as String? ?? '',
    attackSucceeded: json['attack_succeeded'] as bool? ?? false,
    guardrailBlocked: json['guardrail_blocked'] as bool? ?? false,
    guardrailViolations: _strings(json['guardrail_violations']),
    markersHit: _strings(json['markers_hit']),
    answerExcerpt: json['answer_excerpt'] as String? ?? '',
    conclusive: json['conclusive'] as bool? ?? true,
    becameRefusal: json['became_refusal'] as bool? ?? false,
  );
}

class InjectionResult {
  final bool readOnlyScopeOk;
  final List<String> scopeOffenders;
  final double attackSuccessRateBefore;
  final double attackSuccessRateAfter;
  final double availabilityImpactRate;
  final int inconclusiveAttempts;
  final List<AttackOutcome> undefended;
  final List<AttackOutcome> defended;
  final double sanitizeUsPerChunk;
  final double guardrailUsPerAnswer;
  final double trajectoryPassRateBaseline;
  final double trajectoryPassRateAfterDefense;
  final List<String> residualVulnerabilities;

  const InjectionResult({
    required this.readOnlyScopeOk,
    required this.scopeOffenders,
    required this.attackSuccessRateBefore,
    required this.attackSuccessRateAfter,
    required this.availabilityImpactRate,
    required this.inconclusiveAttempts,
    required this.undefended,
    required this.defended,
    required this.sanitizeUsPerChunk,
    required this.guardrailUsPerAnswer,
    required this.trajectoryPassRateBaseline,
    required this.trajectoryPassRateAfterDefense,
    required this.residualVulnerabilities,
  });

  factory InjectionResult.fromJson(Map<String, dynamic> json) {
    final overhead = json['overhead'] as Map<String, dynamic>? ?? {};
    List<AttackOutcome> outcomes(Object? v) => ((v as List?) ?? [])
        .map((e) => AttackOutcome.fromJson(e as Map<String, dynamic>))
        .toList();
    return InjectionResult(
      readOnlyScopeOk: json['read_only_scope_ok'] as bool? ?? false,
      scopeOffenders: _strings(json['scope_offenders']),
      attackSuccessRateBefore: _d(json['attack_success_rate_before']),
      attackSuccessRateAfter: _d(json['attack_success_rate_after']),
      availabilityImpactRate: _d(json['availability_impact_rate']),
      inconclusiveAttempts: _i(json['inconclusive_attempts']),
      undefended: outcomes(json['undefended']),
      defended: outcomes(json['defended']),
      sanitizeUsPerChunk: _d(overhead['sanitize_us_per_chunk']),
      guardrailUsPerAnswer: _d(overhead['guardrail_us_per_answer']),
      trajectoryPassRateBaseline: _d(json['trajectory_pass_rate_baseline']),
      trajectoryPassRateAfterDefense: _d(
        json['trajectory_pass_rate_after_defense'],
      ),
      residualVulnerabilities: _strings(json['residual_vulnerabilities']),
    );
  }
}

/// The full Week 8 report.
class TrajectoryReport {
  final String mode;
  final String provider;
  final String model;
  final String collection;

  final TrajectoryMetrics baseline;
  final TrajectoryMetrics mitigated;
  final List<TrajectoryCaseResult> baselineCases;
  final List<TrajectoryCaseResult> mitigatedCases;

  final double outcomePassRate;
  final double trajectoryPassRate;
  final double gap;
  final List<String> falsePositiveCaseIds;

  final TrajectoryCaseResult? exposedTrace;
  final MitigationResult? mitigation;
  final List<ModeDelta> regressionMatrix;
  final InjectionResult? injection;

  const TrajectoryReport({
    required this.mode,
    required this.provider,
    required this.model,
    required this.collection,
    required this.baseline,
    required this.mitigated,
    required this.baselineCases,
    required this.mitigatedCases,
    required this.outcomePassRate,
    required this.trajectoryPassRate,
    required this.gap,
    required this.falsePositiveCaseIds,
    required this.exposedTrace,
    required this.mitigation,
    required this.regressionMatrix,
    required this.injection,
  });

  factory TrajectoryReport.fromJson(Map<String, dynamic> json) {
    List<TrajectoryCaseResult> cases(Object? v) => ((v as List?) ?? [])
        .map((e) => TrajectoryCaseResult.fromJson(e as Map<String, dynamic>))
        .toList();

    final gapJson = json['gap'] as Map<String, dynamic>? ?? {};
    final traceJson = json['exposed_trace'] as Map<String, dynamic>?;
    final mitigationJson = json['mitigation'] as Map<String, dynamic>?;
    final injectionJson = json['injection'] as Map<String, dynamic>?;

    final baselineCases = cases(json['baseline_cases']);
    // The exposed trace is a projection of one baseline case, so resolve it
    // back to the full case object rather than parsing a second, thinner copy.
    TrajectoryCaseResult? exposed;
    if (traceJson != null) {
      final id = traceJson['case_id'] as String?;
      for (final c in baselineCases) {
        if (c.caseId == id) {
          exposed = c;
          break;
        }
      }
    }

    return TrajectoryReport(
      mode: json['mode'] as String? ?? '',
      provider: json['provider'] as String? ?? '',
      model: json['model'] as String? ?? '',
      collection: json['collection'] as String? ?? '',
      baseline: TrajectoryMetrics.fromJson(
        json['baseline'] as Map<String, dynamic>? ?? {},
      ),
      mitigated: TrajectoryMetrics.fromJson(
        json['mitigated'] as Map<String, dynamic>? ?? {},
      ),
      baselineCases: baselineCases,
      mitigatedCases: cases(json['mitigated_cases']),
      outcomePassRate: _d(gapJson['outcome_pass_rate']),
      trajectoryPassRate: _d(gapJson['trajectory_pass_rate']),
      gap: _d(gapJson['gap']),
      falsePositiveCaseIds: _strings(gapJson['false_positive_case_ids']),
      exposedTrace: exposed,
      mitigation: mitigationJson == null
          ? null
          : MitigationResult.fromJson(mitigationJson),
      regressionMatrix: ((json['regression_matrix'] as List?) ?? [])
          .map((e) => ModeDelta.fromJson(e as Map<String, dynamic>))
          .toList(),
      injection: injectionJson == null
          ? null
          : InjectionResult.fromJson(injectionJson),
    );
  }
}
