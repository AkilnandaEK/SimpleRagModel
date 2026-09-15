/// Typed models for the "Agent vs Workflow Benchmark" API response
/// (POST /api/benchmark/run). All values come from the backend; the UI never
/// recomputes benchmark metrics.
library;

/// Aggregated metrics for a single architecture (agent or workflow).
class ArchitectureBenchmarkResult {
  final String architecture;
  final double successRate;
  final int successfulCount;
  final int totalCount;
  final double p50LatencyMs;
  final double p99LatencyMs;
  final double avgInputTokens;
  final double avgOutputTokens;
  final double avgTotalTokens;
  final int totalTokens;
  final double totalCostUsd;
  final double avgCostPerRun;
  final double costPerSuccess;

  const ArchitectureBenchmarkResult({
    required this.architecture,
    required this.successRate,
    required this.successfulCount,
    required this.totalCount,
    required this.p50LatencyMs,
    required this.p99LatencyMs,
    required this.avgInputTokens,
    required this.avgOutputTokens,
    required this.avgTotalTokens,
    required this.totalTokens,
    required this.totalCostUsd,
    required this.avgCostPerRun,
    required this.costPerSuccess,
  });

  factory ArchitectureBenchmarkResult.fromJson(Map<String, dynamic> json) {
    double d(Object? value) => (value as num?)?.toDouble() ?? 0.0;
    int i(Object? value) => (value as num?)?.toInt() ?? 0;
    return ArchitectureBenchmarkResult(
      architecture: json['architecture'] as String? ?? '',
      successRate: d(json['success_rate']),
      successfulCount: i(json['successful_count']),
      totalCount: i(json['total_count']),
      p50LatencyMs: d(json['p50_latency_ms']),
      p99LatencyMs: d(json['p99_latency_ms']),
      avgInputTokens: d(json['avg_input_tokens']),
      avgOutputTokens: d(json['avg_output_tokens']),
      avgTotalTokens: d(json['avg_total_tokens']),
      totalTokens: i(json['total_tokens']),
      totalCostUsd: d(json['total_cost_usd']),
      avgCostPerRun: d(json['avg_cost_per_run']),
      costPerSuccess: d(json['cost_per_success']),
    );
  }
}

/// One scenario's outcome for both architectures.
class ScenarioResult {
  final String id;
  final String level;
  final bool isNegativeCase;
  final String question;
  final bool agentCorrect;
  final String agentMatchType;
  final bool workflowCorrect;
  final String workflowMatchType;

  const ScenarioResult({
    required this.id,
    required this.level,
    required this.isNegativeCase,
    required this.question,
    required this.agentCorrect,
    required this.agentMatchType,
    required this.workflowCorrect,
    required this.workflowMatchType,
  });

  factory ScenarioResult.fromJson(Map<String, dynamic> json) {
    return ScenarioResult(
      id: json['id'] as String? ?? '',
      level: json['level'] as String? ?? '',
      isNegativeCase: json['is_negative_case'] as bool? ?? false,
      question: json['question'] as String? ?? '',
      agentCorrect: json['agent_correct'] as bool? ?? false,
      agentMatchType: json['agent_match_type'] as String? ?? '',
      workflowCorrect: json['workflow_correct'] as bool? ?? false,
      workflowMatchType: json['workflow_match_type'] as String? ?? '',
    );
  }
}

/// Full response of a benchmark run.
class BenchmarkResult {
  final List<String> scenarioIds;
  final ArchitectureBenchmarkResult agent;
  final ArchitectureBenchmarkResult workflow;
  final List<ScenarioResult> scenarioResults;

  const BenchmarkResult({
    required this.scenarioIds,
    required this.agent,
    required this.workflow,
    required this.scenarioResults,
  });

  factory BenchmarkResult.fromJson(Map<String, dynamic> json) {
    return BenchmarkResult(
      scenarioIds: (json['scenario_ids'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      agent: ArchitectureBenchmarkResult.fromJson(
        json['agent'] as Map<String, dynamic>,
      ),
      workflow: ArchitectureBenchmarkResult.fromJson(
        json['workflow'] as Map<String, dynamic>,
      ),
      scenarioResults: (json['scenario_results'] as List<dynamic>? ?? [])
          .map((e) => ScenarioResult.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }

  /// Winner of the benchmark, based on SUCCESS RATE only. 'Draw' when equal.
  String get winnerLabel {
    if (agent.successRate > workflow.successRate) return 'Agent';
    if (workflow.successRate > agent.successRate) return 'Workflow';
    return 'Draw';
  }

  double get winnerSuccessRate =>
      winnerLabel == 'Agent' ? agent.successRate : workflow.successRate;

  int get agentPassCount =>
      scenarioResults.where((r) => r.agentCorrect).length;

  int get workflowPassCount =>
      scenarioResults.where((r) => r.workflowCorrect).length;

  int get scenarioCount =>
      scenarioResults.isEmpty ? (scenarioIds.length) : scenarioResults.length;

  /// Human-readable insight lines derived from the benchmark numbers.
  ///
  /// Kept factual: states which architecture won by success rate, calls out a
  /// couple of secondary efficiency observations, and never makes an absolute
  /// claim about either architecture.
  List<String> get insightLines {
    final total = scenarioCount;
    final lines = <String>[];

    if (agent.successRate > workflow.successRate) {
      lines.add(
        'Agent achieved a higher success rate (${_pct(agent.successRate)} vs '
        '${_pct(workflow.successRate)}) on these $total scenarios.',
      );
    } else if (workflow.successRate > agent.successRate) {
      lines.add(
        'Workflow achieved a higher success rate (${_pct(workflow.successRate)} vs '
        '${_pct(agent.successRate)}) on these $total scenarios.',
      );
    } else {
      lines.add(
        'Both architectures achieved the same success rate '
        '(${_pct(agent.successRate)}) on these $total scenarios.',
      );
    }

    final facts = <String>[];
    if (agent.p50LatencyMs < workflow.p50LatencyMs) {
      facts.add(
        'Agent had lower p50 latency '
        '(${_ms(agent.p50LatencyMs)} vs ${_ms(workflow.p50LatencyMs)})',
      );
    } else if (workflow.p50LatencyMs < agent.p50LatencyMs) {
      facts.add(
        'Workflow had lower p50 latency '
        '(${_ms(workflow.p50LatencyMs)} vs ${_ms(agent.p50LatencyMs)})',
      );
    }
    if (agent.totalTokens < workflow.totalTokens) {
      facts.add('Agent used fewer total tokens (${agent.totalTokens} vs ${workflow.totalTokens})');
    } else if (workflow.totalTokens < agent.totalTokens) {
      facts.add('Workflow used fewer total tokens (${workflow.totalTokens} vs ${agent.totalTokens})');
    }
    if (agent.totalCostUsd < workflow.totalCostUsd) {
      facts.add('Agent had lower total cost (${_usd(agent.totalCostUsd)} vs ${_usd(workflow.totalCostUsd)})');
    } else if (workflow.totalCostUsd < agent.totalCostUsd) {
      facts.add('Workflow had lower total cost (${_usd(workflow.totalCostUsd)} vs ${_usd(agent.totalCostUsd)})');
    }
    if (facts.isNotEmpty) {
      lines.add('${facts.take(2).join('; ')}.');
    }

    lines.add(
      'This reflects only these $total selected scenarios, not a general claim '
      'about either architecture.',
    );
    return lines;
  }
}

String _pct(double value) => '${value.toStringAsFixed(1)}%';

String _ms(double value) => '${value.toStringAsFixed(1)} ms';

String _usd(double value) {
  if (value >= 1.0) return '\$${value.toStringAsFixed(2)}';
  if (value >= 0.001) return '\$${value.toStringAsFixed(4)}';
  return '\$${value.toStringAsFixed(6)}';
}