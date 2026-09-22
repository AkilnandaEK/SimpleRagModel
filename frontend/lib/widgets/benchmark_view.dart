import 'dart:math' as math;

import 'package:flutter/material.dart';
import '../models/benchmark_models.dart';
import '../services/api_service.dart';

/// Lifecycle of the benchmark section's run state. The benchmark is only ever
/// started by the user — never automatically on open.
enum BenchmarkStatus { initial, loading, success, error }

/// Full-screen dashboard for the Agent vs Workflow Benchmark.
///
/// Renders the result returned by the backend `POST /api/benchmark/run` and
/// carries all of its own state (initial / loading / success / error), keeping
/// UI separate from the API/service layer and typed models.
class BenchmarkView extends StatefulWidget {
  /// Result of a previous run, shown before the next run starts (never
  /// auto-loaded).
  final BenchmarkResult? previousResult;

  /// Called whenever a finished run produces a result, so the caller can keep
  /// showing it the next time this view opens.
  final ValueChanged<BenchmarkResult>? onResult;

  /// Test seam — when provided, used instead of [ApiService.runBenchmark].
  final Future<BenchmarkResult> Function()? runOverride;

  const BenchmarkView({
    super.key,
    this.previousResult,
    this.onResult,
    this.runOverride,
  });

  @override
  State<BenchmarkView> createState() => _BenchmarkViewState();
}

class _BenchmarkViewState extends State<BenchmarkView> {
  BenchmarkStatus _status = BenchmarkStatus.initial;
  BenchmarkResult? _result;
  String? _errorMessage;

  bool get _isRunning => _status == BenchmarkStatus.loading;

  /// What to display in the dashboard: the fresh result if a run happened,
  /// otherwise the previous result passed in by the caller.
  BenchmarkResult? get _displayResult => _result ?? widget.previousResult;

  Future<void> _run() async {
    if (_isRunning) return; // Prevent duplicate benchmark requests.
    setState(() {
      _status = BenchmarkStatus.loading;
      _errorMessage = null;
    });

    try {
      final result = await (widget.runOverride?.call() ??
          ApiService.runBenchmark());
      if (!mounted) return;
      setState(() {
        _result = result;
        _status = BenchmarkStatus.success;
      });
      widget.onResult?.call(result);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = _cleanError(e);
        _status = BenchmarkStatus.error;
      });
    }
  }

  String _cleanError(Object error) =>
      error.toString().replaceAll('Exception: ', '');

  void _retry() {
    if (_isRunning) return;
    _run();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: const Color(0xFF0F172A),
      surfaceTintColor: Colors.transparent,
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      title: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.compare_arrows_outlined,
                  color: Color(0xFF818CF8)),
              const SizedBox(width: 10),
              Text(
                'Agent vs Workflow Benchmark',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(
                      color: Colors.white,
                      fontWeight: FontWeight.bold,
                    ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            'Standardized 10-scenario evaluation',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: const Color(0xFF94A3B8),
                ),
          ),
        ],
      ),
      content: SizedBox(
        width: 1160,
        height: 760,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              _buildRunButton(),
              const SizedBox(height: 16),
              if (_status == BenchmarkStatus.loading) _buildLoading(),
              if (_status == BenchmarkStatus.error) _buildError(),
              if (_status == BenchmarkStatus.initial &&
                  _displayResult == null)
                _buildEmptyHint(),
              if (_status != BenchmarkStatus.loading &&
                  _status != BenchmarkStatus.error &&
                  _displayResult != null)
                ...[
                  _buildWinner(_displayResult!),
                  const SizedBox(height: 16),
                  _buildComparisonTable(_displayResult!),
                  const SizedBox(height: 16),
                  _buildVisualMetrics(_displayResult!),
                  const SizedBox(height: 16),
                  _buildScenarioTable(_displayResult!),
                  const SizedBox(height: 16),
                  _buildInsight(_displayResult!),
                ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(
            'Close',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: const Color(0xFF818CF8),
                ),
          ),
        ),
      ],
    );
  }

  // ── Primary action ─────────────────────────────────────────────────────────

  Widget _buildRunButton() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: _isRunning
          ? Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Color(0xFF818CF8),
                  ),
                ),
                const SizedBox(width: 12),
                Text(
                  'Running Agent vs Workflow benchmark...',
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: const Color(0xFFCBD5E1),
                        fontWeight: FontWeight.w600,
                      ),
                ),
              ],
            )
          : ElevatedButton.icon(
              onPressed: _run,
              icon: const Icon(Icons.play_arrow_rounded, size: 18),
              label: Text(
                'Run Agent vs Workflow Benchmark',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Colors.white,
                      fontWeight: FontWeight.w600,
                    ),
              ),
              style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFF6366F1),
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(
                  horizontal: 24,
                  vertical: 14,
                ),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(10),
                ),
                elevation: 0,
              ),
            ),
    );
  }

  // ── Loading / empty / error states ─────────────────────────────────────────

  Widget _buildLoading() {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: const Color(0xFF111827),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF6366F1).withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const SizedBox(
            width: 22,
            height: 22,
            child: CircularProgressIndicator(
              strokeWidth: 2.5,
              color: Color(0xFF6366F1),
            ),
          ),
          const SizedBox(width: 14),
          Flexible(
            child: Text(
              'Running Agent vs Workflow benchmark…\nExecuting the standardised '
              '10-scenario evaluation on the backend. This can take a little while.',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: const Color(0xFFCBD5E1),
                    height: 1.5,
                  ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildEmptyHint() {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: const Color(0xFF111827),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Column(
        children: [
          const Icon(Icons.insights_outlined, size: 32, color: Color(0xFF64748B)),
          const SizedBox(height: 12),
          Text(
            'No benchmark run yet',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
          ),
          const SizedBox(height: 6),
          Text(
            'Run the benchmark to compare the Agent and Deterministic Workflow '
            'architectures across the standardised 10-scenario set.',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: const Color(0xFF94A3B8),
                  height: 1.5,
                ),
          ),
        ],
      ),
    );
  }

  Widget _buildError() {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFEF4444).withValues(alpha: 0.5)),
      ),
      child: Column(
        children: [
          const Icon(Icons.error_outline, color: Color(0xFFFCA5A5), size: 34),
          const SizedBox(height: 12),
          Text(
            'Benchmark failed',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: const Color(0xFFFCA5A5),
                  fontWeight: FontWeight.bold,
                ),
          ),
          const SizedBox(height: 8),
          Text(
            _errorMessage ?? 'Unknown error.',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: const Color(0xFFCBD5E1),
                  height: 1.5,
                ),
          ),
          const SizedBox(height: 16),
          ElevatedButton.icon(
            onPressed: _retry,
            icon: const Icon(Icons.refresh, size: 18),
            label: Text(
              'Retry Benchmark',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Colors.white,
                    fontWeight: FontWeight.w600,
                  ),
            ),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF6366F1),
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(
                horizontal: 20,
                vertical: 12,
              ),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(10),
              ),
              elevation: 0,
            ),
          ),
        ],
      ),
    );
  }

  // ── Winner ─────────────────────────────────────────────────────────────────

  Widget _buildWinner(BenchmarkResult result) {
    final winner = result.winnerLabel;
    final Color accent = switch (winner) {
      'Agent' => const Color(0xFF818CF8),
      'Workflow' => const Color(0xFFA78BFA),
      _ => const Color(0xFFFBBF24),
    };

    final subtitle = winner == 'Draw'
        ? 'Both architectures achieved ${result.agent.successRate.toStringAsFixed(1)}% '
            'success rate'
        : '${result.winnerSuccessRate.toStringAsFixed(1)}% success rate';

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [
            accent.withValues(alpha: 0.18),
            const Color(0xFF0F172A),
          ],
        ),
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: accent.withValues(alpha: 0.55)),
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: accent.withValues(alpha: 0.16),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(
              winner == 'Draw'
                  ? Icons.balance
                  : Icons.emoji_events_outlined,
              color: accent,
              size: 30,
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'OVERALL WINNER',
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: const Color(0xFF94A3B8),
                        fontWeight: FontWeight.bold,
                        letterSpacing: 1.0,
                      ),
                ),
                const SizedBox(height: 2),
                Text(
                  winner,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                      ),
                ),
                Text(
                  subtitle,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: const Color(0xFFCBD5E1),
                      ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Text(
            'Winner = highest success rate',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: const Color(0xFF64748B),
                ),
          ),
        ],
      ),
    );
  }

  // ── Side-by-side comparison table ──────────────────────────────────────────

  Widget _buildComparisonTable(BenchmarkResult result) {
    final a = result.agent;
    final w = result.workflow;

    return _sectionCard(
      'Side-by-Side Comparison',
      Column(
        children: [
          _tableHeader(),
          Divider(height: 1, color: const Color(0xFF334155)),
          _tableRow('Success Rate', '${a.successRate.toStringAsFixed(0)}%',
              '${w.successRate.toStringAsFixed(0)}%', lowerBetter: false),
          _tableRow('Successful Runs', '${a.successfulCount}/${a.totalCount}',
              '${w.successfulCount}/${w.totalCount}', lowerBetter: false),
          _tableRow('p50 Latency', '${a.p50LatencyMs.toStringAsFixed(2)} ms',
              '${w.p50LatencyMs.toStringAsFixed(2)} ms', lowerBetter: true),
          _tableRow('p99 Latency', '${a.p99LatencyMs.toStringAsFixed(2)} ms',
              '${w.p99LatencyMs.toStringAsFixed(2)} ms', lowerBetter: true),
          _tableRow('Avg Input Tokens', _fmtToken(a.avgInputTokens),
              _fmtToken(w.avgInputTokens), lowerBetter: true),
          _tableRow('Avg Output Tokens', _fmtToken(a.avgOutputTokens),
              _fmtToken(w.avgOutputTokens), lowerBetter: true),
          _tableRow('Avg Total Tokens', _fmtToken(a.avgTotalTokens),
              _fmtToken(w.avgTotalTokens), lowerBetter: true),
          _tableRow('Total Tokens', '${a.totalTokens}', '${w.totalTokens}',
              lowerBetter: true),
          _tableRow('Total Cost', _fmtUsd(a.totalCostUsd),
              _fmtUsd(w.totalCostUsd), lowerBetter: true),
          _tableRow('Avg Cost / Run', _fmtUsd(a.avgCostPerRun),
              _fmtUsd(w.avgCostPerRun), lowerBetter: true),
          _tableRow('Cost / Successful Run', _fmtUsd(a.costPerSuccess),
              _fmtUsd(w.costPerSuccess), lowerBetter: true),
        ],
      ),
    );
  }

  Widget _tableHeader() {
    return Row(
      children: [
        const Expanded(
          flex: 3,
          child: Text(
            'Metric',
            style: TextStyle(
              color: Color(0xFFA5B4FC),
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        const Expanded(
          flex: 2,
          child: Text(
            'Agent',
            textAlign: TextAlign.right,
            style: TextStyle(
              color: Color(0xFFA5B4FC),
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
        const Expanded(
          flex: 2,
          child: Text(
            'Workflow',
            textAlign: TextAlign.right,
            style: TextStyle(
              color: Color(0xFFA5B4FC),
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ],
    );
  }

  Widget _tableRow(
    String label,
    String agentValue,
    String workflowValue, {
    required bool lowerBetter,
  }) {
    final agentBetter = agentValue != workflowValue &&
        (lowerBetter
            ? _numeric(agentValue) < _numeric(workflowValue)
            : _numeric(agentValue) > _numeric(workflowValue));
    final workflowBetter = !agentBetter && agentValue != workflowValue;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Row(
        children: [
          Expanded(
            flex: 3,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: const Color(0xFFCBD5E1),
                  ),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              agentValue,
              textAlign: TextAlign.right,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: agentBetter
                        ? const Color(0xFF6EE7B7)
                        : Colors.white,
                    fontWeight: agentBetter ? FontWeight.bold : FontWeight.w400,
                  ),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              workflowValue,
              textAlign: TextAlign.right,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: workflowBetter
                        ? const Color(0xFF6EE7B7)
                        : Colors.white,
                    fontWeight:
                        workflowBetter ? FontWeight.bold : FontWeight.w400,
                  ),
            ),
          ),
        ],
      ),
    );
  }

  /// Parse a formatted cell value (e.g. "17.02 ms", "$0.000657") to a number.
  double _numeric(String formatted) =>
      double.tryParse(formatted.replaceAll(RegExp(r'[^0-9.\-]'), '')) ??
      double.nan;

  String _fmtToken(double value) =>
      value == value.roundToDouble() ? value.round().toString() : value.toStringAsFixed(1);

  String _fmtUsd(double value) {
    if (value >= 1.0) return '\$${value.toStringAsFixed(2)}';
    if (value >= 0.001) return '\$${value.toStringAsFixed(4)}';
    return '\$${value.toStringAsFixed(6)}';
  }

  // ── Visual metrics ─────────────────────────────────────────────────────────

  Widget _buildVisualMetrics(BenchmarkResult result) {
    final a = result.agent;
    final w = result.workflow;

    return _sectionCard(
      'Visual Metrics',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _metricBar(
            label: 'Success Rate',
            hint: 'Higher is better',
            lowerBetter: false,
            agentValue: a.successRate,
            workflowValue: w.successRate,
            formatValue: (v) => '${v.toStringAsFixed(0)}%',
          ),
          _metricBar(
            label: 'p50 Latency',
            hint: 'Lower is better',
            lowerBetter: true,
            agentValue: a.p50LatencyMs,
            workflowValue: w.p50LatencyMs,
            formatValue: (v) => '${v.toStringAsFixed(2)} ms',
          ),
          _metricBar(
            label: 'p99 Latency',
            hint: 'Lower is better',
            lowerBetter: true,
            agentValue: a.p99LatencyMs,
            workflowValue: w.p99LatencyMs,
            formatValue: (v) => '${v.toStringAsFixed(2)} ms',
          ),
          _metricBar(
            label: 'Total Tokens',
            hint: 'Lower is better',
            lowerBetter: true,
            agentValue: a.totalTokens.toDouble(),
            workflowValue: w.totalTokens.toDouble(),
            formatValue: (v) => v.round().toString(),
          ),
          _metricBar(
            label: 'Total Cost',
            hint: 'Lower is better',
            lowerBetter: true,
            agentValue: a.totalCostUsd,
            workflowValue: w.totalCostUsd,
            formatValue: (v) => _fmtUsd(v),
          ),
        ],
      ),
    );
  }

  Widget _metricBar({
    required String label,
    required String hint,
    required bool lowerBetter,
    required double agentValue,
    required double workflowValue,
    required String Function(double) formatValue,
  }) {
    final maxValue = math.max(agentValue, workflowValue);
    final aFraction = maxValue <= 0 ? 0.0 : agentValue / maxValue;
    final wFraction = maxValue <= 0 ? 0.0 : workflowValue / maxValue;

    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w600,
                      ),
                ),
              ),
              Text(
                hint,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                      color: const Color(0xFF64748B),
                    ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          _barRow(
            'Agent',
            agentValue,
            aFraction,
            lowerBetter,
            workflowValue,
            formatValue,
          ),
          const SizedBox(height: 6),
          _barRow(
            'Workflow',
            workflowValue,
            wFraction,
            lowerBetter,
            agentValue,
            formatValue,
          ),
        ],
      ),
    );
  }

  Widget _barRow(
    String name,
    double value,
    double fraction,
    bool lowerBetter,
    double otherValue,
    String Function(double) formatValue,
  ) {
    final isBetter = lowerBetter ? value < otherValue : value > otherValue;
    final isTie = value == otherValue;
    final barColor =
        isTie || !isBetter ? const Color(0xFF6366F1) : const Color(0xFF10B981);

    return Row(
      children: [
        SizedBox(
          width: 68,
          child: Text(
            name,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: const Color(0xFF94A3B8),
                ),
          ),
        ),
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: Container(
              height: 12,
              color: const Color(0xFF1E293B),
              alignment: Alignment.centerLeft,
              child: FractionallySizedBox(
                widthFactor: fraction.clamp(0.02, 1.0),
                child: Container(color: barColor),
              ),
            ),
          ),
        ),
        const SizedBox(width: 12),
        Flexible(
          child: Row(
            mainAxisSize: MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              if (isBetter) ...[
                const Icon(Icons.check_circle, size: 13, color: Color(0xFF6EE7B7)),
                const SizedBox(width: 4),
              ],
              Text(
                formatValue(value),
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: isBetter
                          ? const Color(0xFF6EE7B7)
                          : Colors.white,
                      fontWeight: FontWeight.w600,
                    ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  // ── Scenario results ───────────────────────────────────────────────────────

  Widget _buildScenarioTable(BenchmarkResult result) {
    final total = result.scenarioCount;

    return _sectionCard(
      'Scenario Results',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: DataTable(
              headingRowColor: WidgetStateProperty.all(const Color(0xFF1E293B)),
              dataRowColor: WidgetStateProperty.all(const Color(0xFF0F172A)),
              dividerThickness: 0.6,
              columnSpacing: 22,
              columns: const ['Scenario', 'Level', 'Agent', 'Workflow']
                  .map(
                    (header) => DataColumn(
                      label: Text(
                        header,
                        style: const TextStyle(
                          color: Color(0xFFA5B4FC),
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  )
                  .toList(),
              rows: result.scenarioResults.map((scenario) {
                return DataRow(
                  cells: [
                    DataCell(
                      Row(
                        children: [
                          Text(
                            scenario.id,
                            style: Theme.of(context)
                                .textTheme
                                .bodyMedium
                                ?.copyWith(
                                  color: const Color(0xFF818CF8),
                                  fontWeight: FontWeight.bold,
                                ),
                          ),
                          if (scenario.isNegativeCase) ...[
                            const SizedBox(width: 8),
                            Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 6,
                                vertical: 1,
                              ),
                              decoration: BoxDecoration(
                                color: const Color(0xFFFBBF24)
                                    .withValues(alpha: 0.12),
                                borderRadius: BorderRadius.circular(4),
                                border: Border.all(
                                  color: const Color(0xFFFBBF24)
                                      .withValues(alpha: 0.35),
                                ),
                              ),
                              child: const Text(
                                'NEG',
                                style: TextStyle(
                                  color: Color(0xFFFBBF24),
                                  fontSize: 9,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ),
                          ],
                        ],
                      ),
                    ),
                    DataCell(
                      Text(
                        scenario.level,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: const Color(0xFFCBD5E1),
                            ),
                      ),
                    ),
                    DataCell(_statusChip(scenario.agentCorrect)),
                    DataCell(_statusChip(scenario.workflowCorrect)),
                  ],
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              _runSummaryChip('Agent', result.agentPassCount, total),
              const SizedBox(width: 10),
              _runSummaryChip('Workflow', result.workflowPassCount, total),
            ],
          ),
        ],
      ),
    );
  }

  Widget _statusChip(bool passed) {
    final color = passed ? const Color(0xFF10B981) : const Color(0xFFEF4444);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.45)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(passed ? Icons.check_circle_outline : Icons.cancel_outlined,
              size: 12, color: color),
          const SizedBox(width: 4),
          Text(
            passed ? 'Passed' : 'Failed',
            style: TextStyle(
              color: color,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }

  Widget _runSummaryChip(String name, int passed, int total) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '$name: ',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: const Color(0xFF94A3B8),
                ),
          ),
          Text(
            '$passed/$total',
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
          ),
        ],
      ),
    );
  }

  // ── Benchmark insight ──────────────────────────────────────────────────────

  Widget _buildInsight(BenchmarkResult result) {
    final lines = result.insightLines;
    return _sectionCard(
      'Benchmark Insight',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final line in lines)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Padding(
                    padding: EdgeInsets.only(top: 4),
                    child: Icon(Icons.chevron_right,
                        size: 14, color: Color(0xFF818CF8)),
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      line,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            color: const Color(0xFFCBD5E1),
                            height: 1.45,
                          ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  // ── Shared section container ───────────────────────────────────────────────

  Widget _sectionCard(String title, Widget child) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111827),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
          ),
          const SizedBox(height: 12),
          child,
        ],
      ),
    );
  }
}

/// Convenience opener so callers don't need to import [BenchmarkView] internals.
///
/// [previousResult] lets the caller surface the last run's result next time the
/// dashboard opens; [onResult] reports finished runs back to the caller for
/// that purpose. The benchmark is never started automatically on open.
Future<void> showBenchmarkDialog(
  BuildContext context, {
  BenchmarkResult? previousResult,
  ValueChanged<BenchmarkResult>? onResult,
}) {
  return showDialog(
    context: context,
    builder: (_) => BenchmarkView(
      previousResult: previousResult,
      onResult: onResult,
    ),
  );
}