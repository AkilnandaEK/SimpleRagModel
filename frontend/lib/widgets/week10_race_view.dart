import 'package:flutter/material.dart';
import '../models/week10_race_models.dart';
import '../models/week10_recorded_results.dart';
import '../services/api_service.dart';

/// Lifecycle of the Week 10 race section's run state.
///
/// The race is only ever started by the user — never automatically on open.
enum Week10RaceStatus { initial, loading, success, error }

/// Full-screen dashboard for the live Week 10
/// "Single Agent vs Multi-Agent Squad" benchmark.
///
/// Executes the race through `POST /api/benchmark/week10/race` and renders the
/// returned `RaceResult.to_dict()` payload. Every metric in the success state
/// comes from that response: no Week 10 figure is hardcoded here, so the screen
/// always describes the run that just happened rather than the recorded
/// experiment.
///
/// Carries its own state (initial / loading / success / error) with
/// `setState`, matching `BenchmarkView`, and exposes the same `runOverride` test
/// seam so widget tests never issue a real request.
class Week10RaceView extends StatefulWidget {
  /// Result of a previous run, shown before the next run starts (never
  /// auto-loaded).
  final Week10RaceResult? previousResult;

  /// Called whenever a finished run produces a result, so the caller can keep
  /// showing it the next time this view opens.
  final ValueChanged<Week10RaceResult>? onResult;

  /// Test seam — when provided, used instead of [ApiService.runWeek10Race].
  final Future<Week10RaceResult> Function()? runOverride;

  const Week10RaceView({
    super.key,
    this.previousResult,
    this.onResult,
    this.runOverride,
  });

  @override
  State<Week10RaceView> createState() => _Week10RaceViewState();
}

class _Week10RaceViewState extends State<Week10RaceView> {
  Week10RaceStatus _status = Week10RaceStatus.initial;
  Week10RaceResult? _result;
  String? _errorMessage;

  bool get _isRunning => _status == Week10RaceStatus.loading;

  /// What to display: the fresh result if a run happened, otherwise the previous
  /// result handed in by the caller.
  Week10RaceResult? get _displayResult => _result ?? widget.previousResult;

  Future<void> _run() async {
    if (_isRunning) return; // Prevent duplicate race requests.
    setState(() {
      _status = Week10RaceStatus.loading;
      _errorMessage = null;
    });

    try {
      final result =
          await (widget.runOverride?.call() ?? ApiService.runWeek10Race());
      if (!mounted) return;
      setState(() {
        _result = result;
        _status = Week10RaceStatus.success;
      });
      widget.onResult?.call(result);
    } catch (e) {
      if (!mounted) return;
      // The stale result is deliberately not surfaced while in the error state,
      // so a failed run can never be mistaken for a successful one.
      setState(() {
        _errorMessage = _cleanError(e);
        _status = Week10RaceStatus.error;
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
    final result = _displayResult;

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
              const Icon(Icons.hub_outlined, color: Color(0xFFFBBF24)),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Agent vs Multi-Agent Benchmark',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              if (_status == Week10RaceStatus.success) const _LiveBadge(),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            'Week 10 — Live Experiment Result',
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: const Color(0xFF94A3B8)),
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
              if (_isRunning) ...[_buildLoading(), const SizedBox(height: 16)],
              if (_status == Week10RaceStatus.error) _buildError(),
              if (_status == Week10RaceStatus.initial && result == null)
                _buildEmptyHint(),
              if (!_isRunning &&
                  _status != Week10RaceStatus.error &&
                  result != null) ...[
                _buildComparison(result),
                const SizedBox(height: 16),
                _buildCaseTable(result),
                const SizedBox(height: 16),
                _buildHandoffTelemetry(result),
                const SizedBox(height: 16),
                _buildTokenMethodology(result),
                const SizedBox(height: 16),
                _buildPublishedVerdict(),
                const SizedBox(height: 16),
                _buildRecordedFailureExperiment(),
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
            style: Theme.of(
              context,
            ).textTheme.bodyMedium?.copyWith(color: const Color(0xFF818CF8)),
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
                    color: Color(0xFFFBBF24),
                  ),
                ),
                const SizedBox(width: 12),
                Flexible(
                  child: Text(
                    'Running Agent vs Multi-Agent benchmark...',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: const Color(0xFFCBD5E1),
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            )
          : ElevatedButton.icon(
              onPressed: _run,
              icon: const Icon(Icons.play_arrow_rounded, size: 18),
              label: Text(
                'Run Agent vs Multi-Agent Benchmark',
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
        border: Border.all(
          color: const Color(0xFFFBBF24).withValues(alpha: 0.4),
        ),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const SizedBox(
            width: 22,
            height: 22,
            child: CircularProgressIndicator(
              strokeWidth: 2.5,
              color: Color(0xFFFBBF24),
            ),
          ),
          const SizedBox(width: 14),
          Flexible(
            child: Text(
              'Running Agent vs Multi-Agent benchmark...\n'
              'Executing both arms over the Week 10 case set on the backend. '
              'This warms up the embedding model and Chroma first, then makes '
              'real provider calls for the Single Agent arm, so it can take a '
              'little while. There is no progress percentage because the '
              'backend does not report progress.',
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
          const Icon(
            Icons.play_circle_outline,
            size: 32,
            color: Color(0xFF64748B),
          ),
          const SizedBox(height: 12),
          Text(
            'No race executed yet',
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              color: Colors.white,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            'Run the Week 10 race to compare the Single Agent against the '
            'Multi-Agent Squad. The results below come from that execution.',
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
        border: Border.all(
          color: const Color(0xFFEF4444).withValues(alpha: 0.5),
        ),
      ),
      child: Column(
        children: [
          const Icon(Icons.error_outline, color: Color(0xFFFCA5A5), size: 34),
          const SizedBox(height: 12),
          Text(
            'Week 10 race failed',
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
              'Retry',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: Colors.white,
                fontWeight: FontWeight.w600,
              ),
            ),
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFF6366F1),
              foregroundColor: Colors.white,
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
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

  // ── Side-by-side comparison ────────────────────────────────────────────────

  Widget _buildComparison(Week10RaceResult result) {
    final single = result.singleMetrics;
    final multi = result.multiMetrics;

    return _sectionCard(
      'Single Agent vs Multi-Agent Squad',
      Column(
        children: [
          _tableHeader(),
          Divider(height: 1, color: const Color(0xFF334155)),
          _metricRow('Pass Rate', single.passRateLabel, multi.passRateLabel),
          _metricRow('p50 Latency', single.p50Label, multi.p50Label),
          _metricRow('p99 Latency', single.p99Label, multi.p99Label),
          _metricRow(
            'Provider Tokens',
            single.providerTokensLabel,
            multi.providerTokensLabel,
            note:
                '${single.providerTokensSubLabel} · '
                '${multi.providerTokensSubLabel}',
          ),
          _metricRow(
            'Cost Per Question',
            single.costPerQuestionLabel,
            multi.costPerQuestionLabel,
          ),
          _metricRow('Total Cost', single.totalCostLabel, multi.totalCostLabel),
          _metricRow('Handoffs', single.handoffsLabel, multi.handoffsLabel),
          _metricRow(
            'Context Tokens',
            single.contextTokensLabel,
            multi.contextTokensLabel,
          ),
          // The multiplier is defined as Multi-Agent context re-send / Single
          // Agent provider tokens, so it belongs to the Multi-Agent column.
          // The Single Agent is the *baseline* denominator and has no measured
          // context multiplier of its own — never render a fabricated "1.0x".
          _metricRow(
            'Context Re-Send Multiplier',
            'Baseline',
            result.contextResendMultiplierLabel,
            note: 'Multi-Agent context re-send ÷ Single Agent provider tokens',
            emphasiseSecond: true,
          ),
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
            'Single Agent',
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
            'Multi-Agent Squad',
            textAlign: TextAlign.right,
            style: TextStyle(
              color: Color(0xFFFBBF24),
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ),
      ],
    );
  }

  Widget _metricRow(
    String label,
    String singleValue,
    String multiValue, {
    String? note,
    bool emphasiseSecond = false,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 7),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
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
                  singleValue,
                  textAlign: TextAlign.right,
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(color: Colors.white),
                ),
              ),
              Expanded(
                flex: 2,
                child: Text(
                  multiValue,
                  textAlign: TextAlign.right,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: emphasiseSecond
                        ? const Color(0xFFFBBF24)
                        : Colors.white,
                    fontWeight: emphasiseSecond
                        ? FontWeight.w700
                        : FontWeight.w400,
                  ),
                ),
              ),
            ],
          ),
          if (note != null)
            Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Text(
                note,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: const Color(0xFF64748B),
                ),
              ),
            ),
        ],
      ),
    );
  }

  // ── Case results ───────────────────────────────────────────────────────────

  Widget _buildCaseTable(Week10RaceResult result) {
    return _sectionCard(
      'Case Results',
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
              columns:
                  const ['Case', 'Single Agent', 'Multi-Agent', 'Agreement']
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
              rows: result.caseRows.map((row) {
                return DataRow(
                  cells: [
                    DataCell(
                      Text(
                        row.caseId,
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                          color: const Color(0xFFFBBF24),
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                    DataCell(_passChip(row.single?.isCorrect)),
                    DataCell(_passChip(row.multi?.isCorrect)),
                    DataCell(
                      Text(
                        row.agreementLabel,
                        style: TextStyle(
                          color: row.agreement == true
                              ? const Color(0xFF6EE7B7)
                              : row.agreement == false
                              ? const Color(0xFFFCA5A5)
                              : const Color(0xFF64748B),
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                );
              }).toList(),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              _summaryChip('Agreement', result.agreementLabel),
              const SizedBox(width: 10),
              _summaryChip('Cases', '${result.caseRows.length}'),
            ],
          ),
        ],
      ),
    );
  }

  /// `null` means the arm returned no result for this case.
  Widget _passChip(bool? passed) {
    if (passed == null) {
      return const Text(
        '—',
        style: TextStyle(color: Color(0xFF64748B), fontSize: 11),
      );
    }
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
          Icon(
            passed ? Icons.check_circle_outline : Icons.cancel_outlined,
            size: 12,
            color: color,
          ),
          const SizedBox(width: 4),
          Text(
            passed ? 'PASS' : 'FAIL',
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

  Widget _summaryChip(String name, String value) {
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
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: const Color(0xFF94A3B8)),
          ),
          Text(
            value,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Colors.white,
              fontWeight: FontWeight.bold,
            ),
          ),
        ],
      ),
    );
  }

  // ── Handoff telemetry ──────────────────────────────────────────────────────

  Widget _buildHandoffTelemetry(Week10RaceResult result) {
    final handoffs = result.handoffs;
    final workers = handoffs.byDestination;

    return _sectionCard(
      'Multi-Agent Handoff Telemetry',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _kvRow('Total handoffs', '${handoffs.totalHandoffs}'),
          _kvRow('Successful handoffs', '${handoffs.successfulHandoffs}'),
          _kvRow('Failed handoffs', '${handoffs.failedHandoffs}'),
          _kvRow('Total context tokens', handoffs.contextTokensLabel),
          _kvRow(
            'Context Re-Send Multiplier',
            result.contextResendMultiplierLabel,
            emphasise: true,
          ),
          const SizedBox(height: 12),
          if (workers.isEmpty)
            const Text(
              'No agent-to-agent handoffs were recorded in this run.',
              style: TextStyle(color: Color(0xFF64748B), fontSize: 12),
            )
          else
            for (final worker in workers) ...[
              _kvRow(
                worker.destination,
                '${worker.contextTokensLabel(handoffs.totalContextTokens)}'
                '  ·  ${worker.shareLabel}',
              ),
            ],
        ],
      ),
    );
  }

  Widget _kvRow(String label, String value, {bool emphasise = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 3,
            child: Text(
              label,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(color: const Color(0xFFCBD5E1)),
            ),
          ),
          Expanded(
            flex: 2,
            child: Text(
              value,
              textAlign: TextAlign.right,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: emphasise ? const Color(0xFFFBBF24) : Colors.white,
                fontWeight: emphasise ? FontWeight.w700 : FontWeight.w400,
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ── Token methodology ──────────────────────────────────────────────────────

  Widget _buildTokenMethodology(Week10RaceResult result) {
    final handoffs = result.handoffs;

    return _sectionCard(
      'Token Methodology',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Provider tokens and context tokens measure two different things and '
            'are not interchangeable.',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: const Color(0xFFCBD5E1),
              height: 1.45,
            ),
          ),
          const SizedBox(height: 10),
          _bullet(
            'Provider tokens are model-native BPE counts of real LLM calls. '
            'The Multi-Agent Squad makes no LLM calls in its workers, so its '
            'provider tokens are unavailable — not zero.',
          ),
          _bullet(
            'Context tokens are estimated — ${handoffs.contextTokenMethod} — and '
            'measure agent-to-agent context re-send volume. They are NOT '
            'model-native BPE tokens.',
          ),
          if (handoffs.providerTokenNote.isNotEmpty)
            _bullet(handoffs.providerTokenNote)
          else if (handoffs.contextTokenNote.isNotEmpty)
            _bullet(handoffs.contextTokenNote),
        ],
      ),
    );
  }

  Widget _bullet(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.only(top: 4),
            child: Icon(
              Icons.chevron_right,
              size: 14,
              color: Color(0xFFFBBF24),
            ),
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              text,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: const Color(0xFF94A3B8),
                height: 1.45,
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ── Published verdict (static documentation, not a live computation) ───────

  Widget _buildPublishedVerdict() {
    final verdict = Week10PublishedVerdict.week10;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF111827),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: const Color(0xFFEF4444).withValues(alpha: 0.45),
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.gavel_outlined,
                size: 18,
                color: Color(0xFFF87171),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Published Week 10 Verdict',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: Colors.white,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              const _StaticBadge(),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'Documented conclusion from the Week 10 investigation. This is NOT '
            'recomputed from the run above and will not change when you re-run '
            'the benchmark.',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: const Color(0xFF94A3B8),
              height: 1.4,
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 12,
                  vertical: 6,
                ),
                decoration: BoxDecoration(
                  color: const Color(0xFFEF4444).withValues(alpha: 0.16),
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(
                    color: const Color(0xFFEF4444).withValues(alpha: 0.5),
                  ),
                ),
                child: Text(
                  verdict.decision,
                  style: const TextStyle(
                    color: Color(0xFFF87171),
                    fontSize: 15,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 1.0,
                  ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  verdict.headline,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: const Color(0xFFCBD5E1),
                    height: 1.45,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          for (final reason in verdict.reasons) _bullet(reason),
          const SizedBox(height: 4),
          Text(
            verdict.revisitCondition,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: const Color(0xFF64748B),
              height: 1.4,
            ),
          ),
        ],
      ),
    );
  }

  // ── Recorded failure experiment (separate injection run) ───────────────────

  Widget _buildRecordedFailureExperiment() {
    final failure = Week10RecordedFailureExperiment.week10;

    return _sectionCard(
      'Recorded Failure Experiment',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(
                Icons.science_outlined,
                size: 16,
                color: Color(0xFF94A3B8),
              ),
              const SizedBox(width: 8),
              const Expanded(child: _StaticBadge()),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            'A separate HTTP 500 injection run documented in failure_case.md. '
            'The benchmark above executes the clean baseline race — it does not '
            'perform this injection.',
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
              color: const Color(0xFF94A3B8),
              height: 1.4,
            ),
          ),
          const SizedBox(height: 12),
          Text(
            'Case ${failure.caseId}: ${failure.summary}',
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: Colors.white,
              fontWeight: FontWeight.w600,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            failure.outcome,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: const Color(0xFFCBD5E1),
              height: 1.45,
            ),
          ),
          const SizedBox(height: 12),
          for (final step in failure.steps)
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Icon(
                      switch (step.tone) {
                        Week10StepTone.bad => Icons.cancel_outlined,
                        Week10StepTone.good => Icons.check_circle_outline,
                        Week10StepTone.neutral => Icons.remove_circle_outline,
                      },
                      size: 14,
                      color: switch (step.tone) {
                        Week10StepTone.bad => const Color(0xFFF87171),
                        Week10StepTone.good => const Color(0xFF6EE7B7),
                        Week10StepTone.neutral => const Color(0xFF94A3B8),
                      },
                    ),
                  ),
                  const SizedBox(width: 8),
                  SizedBox(
                    width: 190,
                    child: Text(
                      step.label,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: const Color(0xFFCBD5E1),
                      ),
                    ),
                  ),
                  Expanded(
                    child: Text(
                      step.detail,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: const Color(0xFF94A3B8),
                        height: 1.4,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          const SizedBox(height: 10),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFFFBBF24).withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: const Color(0xFFFBBF24).withValues(alpha: 0.35),
              ),
            ),
            child: Text(
              failure.evaluatorLimitation,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: const Color(0xFFFDE68A),
                height: 1.45,
              ),
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

/// Marks the success state as the output of the execution that just ran.
class _LiveBadge extends StatelessWidget {
  const _LiveBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: const Color(0xFF10B981).withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(
          color: const Color(0xFF10B981).withValues(alpha: 0.5),
        ),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.bolt, size: 12, color: Color(0xFF6EE7B7)),
          SizedBox(width: 4),
          Text(
            'LIVE',
            style: TextStyle(
              color: Color(0xFF6EE7B7),
              fontSize: 10,
              fontWeight: FontWeight.w800,
              letterSpacing: 0.8,
            ),
          ),
        ],
      ),
    );
  }
}

/// Marks a section as static documentation rather than a live computation.
class _StaticBadge extends StatelessWidget {
  const _StaticBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: const Color(0xFF64748B).withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(
          color: const Color(0xFF64748B).withValues(alpha: 0.5),
        ),
      ),
      child: const Text(
        'PUBLISHED · STATIC',
        style: TextStyle(
          color: Color(0xFF94A3B8),
          fontSize: 10,
          fontWeight: FontWeight.w800,
          letterSpacing: 0.6,
        ),
      ),
    );
  }
}

/// Convenience opener so callers don't need to import [Week10RaceView] internals.
///
/// [previousResult] lets the caller surface the last run's result next time the
/// dashboard opens; [onResult] reports finished runs back to the caller for that
/// purpose. The race is never started automatically on open.
Future<void> showWeek10RaceDialog(
  BuildContext context, {
  Week10RaceResult? previousResult,
  ValueChanged<Week10RaceResult>? onResult,
}) {
  return showDialog(
    context: context,
    builder: (_) =>
        Week10RaceView(previousResult: previousResult, onResult: onResult),
  );
}
