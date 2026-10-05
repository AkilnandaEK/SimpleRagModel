/// Live Week 10 "Single Agent vs Multi-Agent Squad" models.
///
/// These mirror `RaceResult.to_dict()` from `eval/week10_race_runner.py`
/// one-to-one. Every field is populated from the
/// `POST /api/benchmark/week10/race` response — no Week 10 figure is hardcoded
/// here, so the UI always reflects the run that just happened.
///
/// Token semantics are load-bearing and preserved rather than smoothed over:
///
/// * `providerTotalTokens` is `null` when the arm made no LLM calls. It is
///   never coerced to `0`. [Week10ArmMetrics.providerTokensLabel] renders that
///   as "Unavailable" and [providerTokensSubLabel] as "No LLM calls".
/// * `totalContextTokens` is agent-to-agent context re-send volume estimated
///   with `project_chars_div_4`, *not* model-native BPE tokenization.
///
/// Formatting lives here rather than in widgets so the same value is never
/// rendered inconsistently by two different sections of the view.
library;

import 'package:flutter/foundation.dart';

/// Thousands-separated integer, e.g. `3964` -> `3,964`.
String formatWeek10Int(num value) {
  final negative = value < 0;
  final digits = value.abs().round().toString();
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(',');
    buffer.write(digits[i]);
  }
  return negative ? '-$buffer' : buffer.toString();
}

/// Fixed-precision USD, e.g. `0.000546` -> `$0.000546`.
String formatWeek10Usd(double value) => '\$${value.toStringAsFixed(6)}';

/// Fixed-precision milliseconds, e.g. `19.58` -> `19.58 ms`.
String formatWeek10Ms(double value) => '${value.toStringAsFixed(2)} ms';

/// `1.9584981` -> `2.0x`. Returns `null` when the backend could not compute it.
String? formatWeek10Multiplier(double? value) =>
    value == null ? null : '${value.toStringAsFixed(1)}x';

double? _asDoubleOrNull(Object? value) =>
    value == null ? null : (value as num).toDouble();

int? _asIntOrNull(Object? value) =>
    value == null ? null : (value as num).toInt();

/// Aggregates for one arm, straight from `ArmMetrics.to_dict()`.
@immutable
class Week10ArmMetrics {
  const Week10ArmMetrics({
    required this.arm,
    required this.totalCases,
    required this.passed,
    required this.failed,
    required this.passRate,
    required this.p50LatencyMs,
    required this.p99LatencyMs,
    required this.providerTotalTokens,
    required this.providerTokensAvailable,
    required this.totalContextTokens,
    required this.contextTokenMethod,
    required this.contextTokensEstimated,
    required this.totalCostUsd,
    required this.costPerQuestionUsd,
    required this.totalHandoffs,
    required this.successfulHandoffs,
    required this.failedHandoffs,
  });

  factory Week10ArmMetrics.fromJson(Map<String, dynamic> json) {
    return Week10ArmMetrics(
      arm: json['arm'] as String? ?? '',
      totalCases: (json['total_cases'] as num?)?.toInt() ?? 0,
      passed: (json['passed'] as num?)?.toInt() ?? 0,
      failed: (json['failed'] as num?)?.toInt() ?? 0,
      passRate: (json['pass_rate'] as num?)?.toDouble() ?? 0.0,
      p50LatencyMs: (json['p50_latency_ms'] as num?)?.toDouble() ?? 0.0,
      p99LatencyMs: (json['p99_latency_ms'] as num?)?.toDouble() ?? 0.0,
      providerTotalTokens: _asIntOrNull(json['provider_total_tokens']),
      providerTokensAvailable:
          json['provider_tokens_available'] as bool? ?? false,
      totalContextTokens: (json['total_context_tokens'] as num?)?.toInt() ?? 0,
      contextTokenMethod: json['context_token_method'] as String? ?? '',
      contextTokensEstimated:
          json['context_tokens_estimated'] as bool? ?? false,
      totalCostUsd: (json['total_cost_usd'] as num?)?.toDouble() ?? 0.0,
      costPerQuestionUsd:
          (json['cost_per_question_usd'] as num?)?.toDouble() ?? 0.0,
      totalHandoffs: (json['total_handoffs'] as num?)?.toInt() ?? 0,
      successfulHandoffs: (json['successful_handoffs'] as num?)?.toInt() ?? 0,
      failedHandoffs: (json['failed_handoffs'] as num?)?.toInt() ?? 0,
    );
  }

  final String arm;
  final int totalCases;
  final int passed;
  final int failed;
  final double passRate;
  final double p50LatencyMs;
  final double p99LatencyMs;

  /// `null` when the arm made no LLM calls. Never `0`.
  final int? providerTotalTokens;
  final bool providerTokensAvailable;
  final int totalContextTokens;
  final String contextTokenMethod;
  final bool contextTokensEstimated;
  final double totalCostUsd;
  final double costPerQuestionUsd;
  final int totalHandoffs;
  final int successfulHandoffs;
  final int failedHandoffs;

  /// "2,024" when measured, otherwise "Unavailable" — never "0".
  String get providerTokensLabel =>
      providerTokensAvailable && providerTotalTokens != null
      ? formatWeek10Int(providerTotalTokens!)
      : 'Unavailable';

  /// "Provider tokens" when measured, "No LLM calls" when not.
  String get providerTokensSubLabel =>
      providerTokensAvailable && providerTotalTokens != null
      ? 'Provider tokens'
      : 'No LLM calls';

  /// "30.0% (3/10)".
  String get passRateLabel =>
      '${passRate.toStringAsFixed(1)}% ($passed/$totalCases)';

  /// "19.58 ms".
  String get p50Label => formatWeek10Ms(p50LatencyMs);

  /// "35.97 ms".
  String get p99Label => formatWeek10Ms(p99LatencyMs);

  /// "$0.000055".
  String get costPerQuestionLabel => formatWeek10Usd(costPerQuestionUsd);

  /// "$0.000546".
  String get totalCostLabel => formatWeek10Usd(totalCostUsd);

  /// "0" for a single-agent arm — it has no agent-to-agent handoffs. This is
  /// legitimately measured, unlike unavailable provider tokens.
  String get handoffsLabel => '$totalHandoffs';

  /// "3,964 estimated" — flagged as an estimate, per `contextTokensEstimated`.
  String get contextTokensLabel =>
      totalContextTokens == 0 && !contextTokensEstimated
      ? 'None'
      : contextTokensEstimated
      ? '${formatWeek10Int(totalContextTokens)} estimated'
      : formatWeek10Int(totalContextTokens);
}

/// One case's outcome for one arm, from `CaseResult.to_dict()`.
@immutable
class Week10CaseResult {
  const Week10CaseResult({
    required this.caseId,
    required this.arm,
    required this.level,
    required this.isCorrect,
    required this.matchType,
    required this.latencyMs,
    required this.error,
    required this.providerTotalTokens,
    required this.costUsd,
    required this.handoffCount,
    required this.totalContextTokens,
    required this.workerLlmCalls,
  });

  factory Week10CaseResult.fromJson(Map<String, dynamic> json) {
    return Week10CaseResult(
      caseId: json['case_id'] as String? ?? '',
      arm: json['arm'] as String? ?? '',
      level: json['level'] as String? ?? '',
      isCorrect: json['is_correct'] as bool? ?? false,
      matchType: json['match_type'] as String? ?? '',
      latencyMs: (json['latency_ms'] as num?)?.toDouble() ?? 0.0,
      error: json['error'] as String?,
      providerTotalTokens: _asIntOrNull(json['provider_total_tokens']),
      costUsd: (json['cost_usd'] as num?)?.toDouble() ?? 0.0,
      handoffCount: (json['handoff_count'] as num?)?.toInt() ?? 0,
      totalContextTokens: (json['total_context_tokens'] as num?)?.toInt() ?? 0,
      workerLlmCalls: (json['worker_llm_calls'] as num?)?.toInt() ?? 0,
    );
  }

  final String caseId;
  final String arm;
  final String level;
  final bool isCorrect;
  final String matchType;
  final double latencyMs;
  final String? error;
  final int? providerTotalTokens;
  final double costUsd;
  final int handoffCount;
  final int totalContextTokens;
  final int workerLlmCalls;

  String get outcomeLabel => isCorrect ? 'PASS' : 'FAIL';
}

/// One worker destination's share of context re-send volume.
///
/// `contextSharePercent` is derived once, here, because the backend reports raw
/// per-destination token counts rather than a percentage.
@immutable
class Week10WorkerContext {
  const Week10WorkerContext({
    required this.destination,
    required this.total,
    required this.success,
    required this.failed,
    required this.contextTokens,
    required this.contextSharePercent,
  });

  factory Week10WorkerContext.fromJson(
    String destination,
    Map<String, dynamic> json,
    int summaryTotalContextTokens,
  ) {
    final contextTokens = (json['context_tokens'] as num?)?.toInt() ?? 0;
    return Week10WorkerContext(
      destination: destination,
      total: (json['total'] as num?)?.toInt() ?? 0,
      success: (json['success'] as num?)?.toInt() ?? 0,
      failed: (json['failed'] as num?)?.toInt() ?? 0,
      contextTokens: contextTokens,
      contextSharePercent: summaryTotalContextTokens <= 0
          ? 0.0
          : contextTokens / summaryTotalContextTokens * 100,
    );
  }

  final String destination;
  final int total;
  final int success;
  final int failed;
  final int contextTokens;
  final double contextSharePercent;

  /// "3,674 / 3,964 context tokens".
  String contextTokensLabel(int summaryTotal) =>
      '${formatWeek10Int(contextTokens)} / ${formatWeek10Int(summaryTotal)} context tokens';

  /// "92.7%".
  String get shareLabel => '${contextSharePercent.toStringAsFixed(1)}%';
}

/// Cross-case handoff rollup, from `MultiAgentHandoffSummary.to_dict()`.
@immutable
class Week10HandoffSummary {
  const Week10HandoffSummary({
    required this.totalHandoffs,
    required this.successfulHandoffs,
    required this.failedHandoffs,
    required this.byDestination,
    required this.totalContextTokens,
    required this.contextTokenMethod,
    required this.contextTokensEstimated,
    required this.providerTokensAvailable,
    required this.providerTokenNote,
    required this.contextTokenNote,
  });

  factory Week10HandoffSummary.fromJson(Map<String, dynamic> json) {
    final totalContextTokens =
        (json['total_context_tokens'] as num?)?.toInt() ?? 0;
    final rawByDestination = json['by_destination'];
    final byDestination = <Week10WorkerContext>[];
    if (rawByDestination is Map) {
      // Largest context consumer first: that is the bottleneck the published
      // Week 10 verdict rests on.
      final entries =
          rawByDestination.entries
              .map(
                (entry) => Week10WorkerContext.fromJson(
                  entry.key.toString(),
                  Map<String, dynamic>.from(entry.value as Map),
                  totalContextTokens,
                ),
              )
              .toList()
            ..sort((a, b) => b.contextTokens.compareTo(a.contextTokens));
      byDestination.addAll(entries);
    }

    return Week10HandoffSummary(
      totalHandoffs: (json['total_handoffs'] as num?)?.toInt() ?? 0,
      successfulHandoffs: (json['successful_handoffs'] as num?)?.toInt() ?? 0,
      failedHandoffs: (json['failed_handoffs'] as num?)?.toInt() ?? 0,
      byDestination: byDestination,
      totalContextTokens: totalContextTokens,
      contextTokenMethod: json['context_token_method'] as String? ?? '',
      contextTokensEstimated:
          json['context_tokens_estimated'] as bool? ?? false,
      providerTokensAvailable:
          json['provider_tokens_available'] as bool? ?? false,
      providerTokenNote: json['provider_token_note'] as String? ?? '',
      contextTokenNote: json['context_token_note'] as String? ?? '',
    );
  }

  final int totalHandoffs;
  final int successfulHandoffs;
  final int failedHandoffs;
  final List<Week10WorkerContext> byDestination;
  final int totalContextTokens;
  final String contextTokenMethod;
  final bool contextTokensEstimated;
  final bool providerTokensAvailable;
  final String providerTokenNote;
  final String contextTokenNote;

  /// The worker carrying the most context re-send volume, if any.
  Week10WorkerContext? get topWorker =>
      byDestination.isEmpty ? null : byDestination.first;

  /// "20 (20 success / 0 failed)".
  String get handoffsLabel =>
      '$totalHandoffs ($successfulHandoffs success / $failedHandoffs failed)';

  /// "3,964 estimated".
  String get contextTokensLabel => contextTokensEstimated
      ? '${formatWeek10Int(totalContextTokens)} estimated'
      : formatWeek10Int(totalContextTokens);
}

/// The full live race payload — one representation, straight from
/// `RaceResult.to_dict()`.
@immutable
class Week10RaceResult {
  const Week10RaceResult({
    required this.caseIds,
    required this.failureInjectionEnabled,
    required this.singleCases,
    required this.multiCases,
    required this.singleMetrics,
    required this.multiMetrics,
    required this.handoffs,
    required this.contextResendMultiplier,
  });

  factory Week10RaceResult.fromJson(Map<String, dynamic> json) {
    List<Week10CaseResult> cases(String key) {
      final raw = json[key];
      if (raw is! List) return const <Week10CaseResult>[];
      return raw
          .whereType<Map>()
          .map(
            (item) =>
                Week10CaseResult.fromJson(Map<String, dynamic>.from(item)),
          )
          .toList();
    }

    return Week10RaceResult(
      caseIds: ((json['case_ids'] as List?) ?? const [])
          .map((e) => e.toString())
          .toList(),
      failureInjectionEnabled:
          json['failure_injection_enabled'] as bool? ?? false,
      singleCases: cases('single_agent_cases'),
      multiCases: cases('multi_agent_cases'),
      singleMetrics: Week10ArmMetrics.fromJson(
        Map<String, dynamic>.from(json['single_agent_metrics'] as Map),
      ),
      multiMetrics: Week10ArmMetrics.fromJson(
        Map<String, dynamic>.from(json['multi_agent_metrics'] as Map),
      ),
      handoffs: Week10HandoffSummary.fromJson(
        Map<String, dynamic>.from(json['multi_agent_handoffs'] as Map),
      ),
      contextResendMultiplier: _asDoubleOrNull(
        json['context_resend_multiplier'],
      ),
    );
  }

  final List<String> caseIds;
  final bool failureInjectionEnabled;
  final List<Week10CaseResult> singleCases;
  final List<Week10CaseResult> multiCases;
  final Week10ArmMetrics singleMetrics;
  final Week10ArmMetrics multiMetrics;
  final Week10HandoffSummary handoffs;

  /// Multi-Agent context re-send / Single Agent provider tokens, or `null` when
  /// the denominator was unusable. This is a *ratio of the Multi-Agent arm*;
  /// it is not a measured context multiplier for the Single Agent arm.
  final double? contextResendMultiplier;

  /// "2.0x", or "Unavailable" when the backend could not compute it.
  String get contextResendMultiplierLabel =>
      formatWeek10Multiplier(contextResendMultiplier) ?? 'Unavailable';

  /// Per-case single/multi outcomes joined for the comparison table.
  ///
  /// Order follows [caseIds] so the table mirrors the declared case set.
  List<Week10CaseRow> get caseRows {
    final singleById = {for (final c in singleCases) c.caseId: c};
    final multiById = {for (final c in multiCases) c.caseId: c};
    final ids = caseIds.isEmpty
        ? [
            ...singleById.keys,
            ...multiById.keys.where((id) => !singleById.containsKey(id)),
          ]
        : caseIds;
    return [
      for (final id in ids)
        Week10CaseRow(caseId: id, single: singleById[id], multi: multiById[id]),
    ];
  }

  /// Cases where both arms returned a result **and** graded them identically.
  ///
  /// Rows missing an arm result are not counted as agreement.
  int get agreedCases => caseRows.where((row) => row.agreement == true).length;

  /// "10/10" — agreed cases out of all cases in the run.
  String get agreementLabel => '$agreedCases/${caseRows.length}';
}

/// One row of the case comparison table.
@immutable
class Week10CaseRow {
  const Week10CaseRow({
    required this.caseId,
    required this.single,
    required this.multi,
  });

  final String caseId;
  final Week10CaseResult? single;
  final Week10CaseResult? multi;

  /// `true`/`false` when both arms have a result, otherwise `null`.
  bool? get agreement => (single == null || multi == null)
      ? null
      : single!.isCorrect == multi!.isCorrect;

  /// "Agreed" / "Disagreed", or "—" when either arm is missing.
  String get agreementLabel {
    final agreed = agreement;
    if (agreed == null) return '—';
    return agreed ? 'Agreed' : 'Disagreed';
  }
}
