import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import '../models/trajectory_models.dart';
import '../services/api_service.dart';

/// Lifecycle of the trajectory suite's run state. The suite is only ever
/// started by the user — never automatically on open, because a live run costs
/// real provider calls.
enum TrajectoryStatus { initial, loading, success, error }

const _bg = Color(0xFF0B0F19);
const _panel = Color(0xFF0F172A);
const _border = Color(0xFF1E293B);
const _muted = Color(0xFF64748B);
const _text = Color(0xFFCBD5E1);
const _indigo = Color(0xFF6366F1);
const _indigoLight = Color(0xFF818CF8);
const _green = Color(0xFF10B981);
const _red = Color(0xFFEF4444);
const _amber = Color(0xFFF59E0B);

/// The "Trajectory Evals" workspace tab.
///
/// Renders the report returned by `POST /api/trajectory/run`. Every figure shown
/// is computed by the backend metrics engine — this widget formats numbers and
/// never derives a rate, a gap or a delta of its own, so the tab and the CLI
/// report cannot drift apart.
class TrajectoryView extends StatefulWidget {
  /// Result of a previous run, shown before the next run starts.
  final TrajectoryReport? previousReport;

  /// Called whenever a finished run produces a report, so the caller can keep
  /// showing it the next time this tab is opened.
  final ValueChanged<TrajectoryReport>? onReport;

  /// Test seam — when provided, used instead of [ApiService.runTrajectoryEval].
  final Future<TrajectoryReport> Function()? runOverride;

  const TrajectoryView({
    super.key,
    this.previousReport,
    this.onReport,
    this.runOverride,
  });

  @override
  State<TrajectoryView> createState() => _TrajectoryViewState();
}

class _TrajectoryViewState extends State<TrajectoryView> {
  TrajectoryStatus _status = TrajectoryStatus.initial;
  TrajectoryReport? _report;
  String? _errorMessage;
  int _section = 0;

  // Run configuration. Offline mode is offered but flagged, because the
  // deterministic reasoner always walks the same path and so cannot expose a
  // gap — see the banner in the controls row.
  String _mode = 'live';
  String _provider = 'groq';
  bool _includeInjection = true;

  /// Models this loop is known to drive end-to-end, best first.
  ///
  /// Leaving this unset falls back to whatever `GROQ_MODEL` happens to be in
  /// `.env`, which is how a run can silently end up on a model that cannot
  /// complete a single case. The choice is explicit here instead.
  static const _groqModels = <String>[
    'openai/gpt-oss-120b',
    'qwen/qwen3.8-27b',
    'openai/gpt-oss-20b',
    'groq/compound-mini',
  ];
  static const _geminiModels = <String>['gemini-3.5-flash'];

  String _model = _groqModels.first;

  List<String> get _modelsForProvider =>
      _provider == 'gemini' ? _geminiModels : _groqModels;

  bool get _isRunning => _status == TrajectoryStatus.loading;
  TrajectoryReport? get _display => _report ?? widget.previousReport;

  Future<void> _run() async {
    if (_isRunning) return; // Prevent duplicate suite requests.
    setState(() {
      _status = TrajectoryStatus.loading;
      _errorMessage = null;
    });

    try {
      final report = await (widget.runOverride?.call() ??
          ApiService.runTrajectoryEval(
            mode: _mode,
            provider: _provider,
            model: _model,
            includeInjection: _includeInjection,
          ));
      if (!mounted) return;
      setState(() {
        _report = report;
        _status = TrajectoryStatus.success;
      });
      widget.onReport?.call(report);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.toString().replaceAll('Exception: ', '');
        _status = TrajectoryStatus.error;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final report = _display;
    return Container(
      color: _bg,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _header(),
          if (_status == TrajectoryStatus.error) _errorBanner(),
          Expanded(
            child: _isRunning
                ? _loading()
                : report == null
                    ? _empty()
                    : _report_(report),
          ),
        ],
      ),
    );
  }

  // ── Header ────────────────────────────────────────────────────────────────

  Widget _header() {
    final report = _display;
    return Container(
      padding: const EdgeInsets.fromLTRB(28, 22, 28, 18),
      decoration: const BoxDecoration(
        color: _panel,
        border: Border(bottom: BorderSide(color: _border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Wrap, not Row: the title plus four controls do not fit on one line
          // in a narrow window, and a hard Row overflows rather than reflowing.
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            runSpacing: 12,
            spacing: 16,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.route_outlined,
                      color: _indigoLight, size: 22),
                  const SizedBox(width: 10),
                  Text(
                    'Trajectory Evals',
                    style: GoogleFonts.outfit(
                      color: Colors.white,
                      fontSize: 20,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(width: 12),
                  _chip('Week 8', _indigo),
                ],
              ),
              Wrap(
                crossAxisAlignment: WrapCrossAlignment.center,
                spacing: 10,
                runSpacing: 10,
                children: [
                  _modeDropdown(),
                  _providerDropdown(),
                  _modelDropdown(),
                  _injectionToggle(),
                  ElevatedButton.icon(
                    onPressed: _isRunning ? null : _run,
                    icon: _isRunning
                        ? const SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.play_arrow_rounded, size: 18),
                    label: Text(
                      _isRunning ? 'Running…' : 'Run suite',
                      style: GoogleFonts.inter(fontWeight: FontWeight.w600),
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: _indigo,
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 18, vertical: 14),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                      elevation: 0,
                    ),
                  ),
                ],
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            report == null
                ? '10 documentation queries · asserts the path taken, not just the answer'
                : 'Ran ${report.baseline.totalCases} queries on '
                    '${report.provider}:${report.model} in ${report.mode} mode '
                    '· collection ${report.collection}',
            style: GoogleFonts.inter(color: _muted, fontSize: 12),
          ),
          if (_mode == 'offline') ...[
            const SizedBox(height: 10),
            _banner(
              Icons.info_outline,
              _amber,
              'Offline mode uses the deterministic reasoner, which always walks '
              'the same path. It cannot expose an outcome-vs-trajectory gap — '
              'use live mode for a meaningful measurement.',
            ),
          ],
        ],
      ),
    );
  }

  Widget _modeDropdown() => _dropdown(
        label: 'Mode',
        value: _mode,
        items: const ['live', 'offline'],
        onChanged: (v) => setState(() => _mode = v),
      );

  Widget _providerDropdown() => _dropdown(
        label: 'Provider',
        value: _provider,
        items: const ['groq', 'gemini'],
        onChanged: (v) => setState(() {
          _provider = v;
          // The previous selection belongs to the old provider's catalogue, so
          // it would be an invalid DropdownButton value after the switch.
          _model = _modelsForProvider.first;
        }),
      );

  Widget _modelDropdown() => _dropdown(
        label: 'Model',
        value: _model,
        items: _modelsForProvider,
        onChanged: (v) => setState(() => _model = v),
      );

  Widget _dropdown({
    required String label,
    required String value,
    required List<String> items,
    required ValueChanged<String> onChanged,
  }) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 2),
      decoration: BoxDecoration(
        color: _bg,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('$label  ',
              style: GoogleFonts.inter(color: _muted, fontSize: 11)),
          DropdownButton<String>(
            value: value,
            underline: const SizedBox.shrink(),
            dropdownColor: _panel,
            isDense: true,
            style: GoogleFonts.inter(color: _text, fontSize: 12),
            items: items
                .map((e) => DropdownMenuItem(value: e, child: Text(e)))
                .toList(),
            onChanged: _isRunning ? null : (v) => v == null ? null : onChanged(v),
          ),
        ],
      ),
    );
  }

  Widget _injectionToggle() {
    return Tooltip(
      message: 'Run the indirect prompt-injection bonus suite',
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Checkbox(
            value: _includeInjection,
            activeColor: _indigo,
            onChanged: _isRunning
                ? null
                : (v) => setState(() => _includeInjection = v ?? true),
          ),
          // Named distinctly from the "Injection" results tab so the two roles
          // (run configuration vs. results view) are not confusable.
          Text('Run injection suite',
              style: GoogleFonts.inter(color: _text, fontSize: 12)),
        ],
      ),
    );
  }

  // ── States ────────────────────────────────────────────────────────────────

  Widget _loading() => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(color: _indigo),
            const SizedBox(height: 20),
            Text('Running the trajectory suite…',
                style: GoogleFonts.inter(color: _text, fontSize: 14)),
            const SizedBox(height: 6),
            Text(
              'Every query runs twice (baseline + mitigated)'
              '${_includeInjection ? ', plus the injection suite' : ''}. '
              'This takes several minutes against a live provider.',
              style: GoogleFonts.inter(color: _muted, fontSize: 12),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      );

  Widget _empty() => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.route_outlined,
                size: 44, color: Colors.white.withValues(alpha: 0.18)),
            const SizedBox(height: 14),
            Text('No trajectory run yet',
                style: GoogleFonts.outfit(
                    color: _text, fontSize: 16, fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            SizedBox(
              width: 460,
              child: Text(
                'An agent that returns the right answer down an unverified path '
                'still passes an outcome test. Run the suite to measure how '
                'often that happens here.',
                style: GoogleFonts.inter(color: _muted, fontSize: 13),
                textAlign: TextAlign.center,
              ),
            ),
          ],
        ),
      );

  Widget _errorBanner() => Container(
        width: double.infinity,
        margin: const EdgeInsets.fromLTRB(28, 16, 28, 0),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: _red.withValues(alpha: 0.12),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: _red.withValues(alpha: 0.4)),
        ),
        child: Row(
          children: [
            const Icon(Icons.error_outline, color: _red, size: 18),
            const SizedBox(width: 10),
            Expanded(
              child: Text(_errorMessage ?? 'Run failed',
                  style: GoogleFonts.inter(color: _text, fontSize: 12.5)),
            ),
            TextButton(
              onPressed: _run,
              child: Text('Retry',
                  style: GoogleFonts.inter(color: _indigoLight, fontSize: 12)),
            ),
          ],
        ),
      );

  // ── Report ────────────────────────────────────────────────────────────────

  Widget _report_(TrajectoryReport r) {
    const sections = [
      'Overview',
      'Cases',
      'False-Positive Trace',
      'Mitigation',
      'Regression',
      'Injection',
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          padding: const EdgeInsets.fromLTRB(28, 14, 28, 0),
          child: Wrap(
            spacing: 8,
            children: [
              for (var i = 0; i < sections.length; i++)
                _sectionTab(sections[i], i),
            ],
          ),
        ),
        const SizedBox(height: 14),
        Expanded(
          child: SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(28, 0, 28, 28),
            child: switch (_section) {
              0 => _overview(r),
              1 => _cases(r),
              2 => _trace(r),
              3 => _mitigation(r),
              4 => _regression(r),
              _ => _injection(r),
            },
          ),
        ),
      ],
    );
  }

  Widget _sectionTab(String label, int index) {
    final active = _section == index;
    return InkWell(
      onTap: () => setState(() => _section = index),
      borderRadius: BorderRadius.circular(8),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
        decoration: BoxDecoration(
          color: active ? _indigo.withValues(alpha: 0.18) : Colors.transparent,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(
            color: active ? _indigo.withValues(alpha: 0.6) : _border,
          ),
        ),
        child: Text(
          label,
          style: GoogleFonts.inter(
            color: active ? Colors.white : _muted,
            fontSize: 12.5,
            fontWeight: active ? FontWeight.w600 : FontWeight.w400,
          ),
        ),
      ),
    );
  }

  // ── Section: Overview ─────────────────────────────────────────────────────

  Widget _overview(TrajectoryReport r) {
    final b = r.baseline;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // IntrinsicHeight so the three cards match height; `stretch` alone
        // inside the enclosing scroll view would force an infinite height.
        IntrinsicHeight(
          child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Expanded(
              child: _statCard(
                'Outcome pass rate',
                '${r.outcomePassRate.toStringAsFixed(1)}%',
                'Answer judged correct',
                _green,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: _statCard(
                'Trajectory pass rate',
                '${r.trajectoryPassRate.toStringAsFixed(1)}%',
                // Without the mitigated figure the headline looks static even
                // when the fix moved it, which reads as "nothing worked".
                'Path judged legitimate · '
                    '${r.mitigated.trajectoryPassRate.toStringAsFixed(1)}% after fix',
                _amber,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: _statCard(
                'THE GAP',
                '${r.gap >= 0 ? '+' : ''}${r.gap.toStringAsFixed(1)} pts',
                '${r.falsePositiveCaseIds.length} right-answer / wrong-path '
                    '${r.falsePositiveCaseIds.length == 1 ? 'case' : 'cases'}',
                r.gap > 0 ? _red : _green,
                emphasis: true,
              ),
            ),
          ],
          ),
        ),
        if (b.erroredCases > 0 || r.mitigated.erroredCases > 0) ...[
          const SizedBox(height: 14),
          _banner(
            Icons.warning_amber_rounded,
            _amber,
            '${b.erroredCases} baseline and ${r.mitigated.erroredCases} '
            'mitigated case(s) aborted on infrastructure errors (provider '
            'quota, network). Those runs carry no failure-mode attribution; '
            'the rates above are over all ${b.totalCases} cases.',
          ),
        ],
        const SizedBox(height: 24),
        _sectionTitle('Trajectory telemetry',
            'The four dimensions, baseline vs after the mitigation'),
        const SizedBox(height: 12),
        _panelBox(
          child: Table(
            columnWidths: const {
              0: FlexColumnWidth(3),
              1: FlexColumnWidth(1.4),
              2: FlexColumnWidth(1.4),
            },
            children: [
              _tableHeader(['Dimension', 'Baseline', 'Mitigated']),
              _metricRow('Tool-Choice Accuracy',
                  '${b.toolChoiceAccuracy.toStringAsFixed(1)}%',
                  '${r.mitigated.toolChoiceAccuracy.toStringAsFixed(1)}%'),
              _metricRow('Argument Validity Rate',
                  '${b.argumentValidityRate.toStringAsFixed(1)}%',
                  '${r.mitigated.argumentValidityRate.toStringAsFixed(1)}%'),
              _metricRow('Step Efficiency',
                  '${b.stepEfficiency.toStringAsFixed(1)}%',
                  '${r.mitigated.stepEfficiency.toStringAsFixed(1)}%'),
              _metricRow('  steps actual / optimal',
                  '${b.totalSteps} / ${b.totalOptimalSteps}',
                  '${r.mitigated.totalSteps} / ${r.mitigated.totalOptimalSteps}',
                  subtle: true),
              _metricRow('Cost p50 (USD / query)',
                  b.costP50Usd.toStringAsFixed(6),
                  r.mitigated.costP50Usd.toStringAsFixed(6)),
              _metricRow('Cost Max (USD / query)',
                  b.costMaxUsd.toStringAsFixed(6),
                  r.mitigated.costMaxUsd.toStringAsFixed(6)),
              _metricRow('  worst-case query', b.costMaxCaseId,
                  r.mitigated.costMaxCaseId,
                  subtle: true),
              _metricRow('Latency p50 (ms)', b.latencyP50Ms.toStringAsFixed(0),
                  r.mitigated.latencyP50Ms.toStringAsFixed(0)),
              _metricRow('Latency p99 (ms)', b.latencyP99Ms.toStringAsFixed(0),
                  r.mitigated.latencyP99Ms.toStringAsFixed(0)),
              _metricRow('Tokens p50 / query', b.tokensP50.toStringAsFixed(0),
                  r.mitigated.tokensP50.toStringAsFixed(0)),
            ],
          ),
        ),
        const SizedBox(height: 10),
        Text(
          'Cost is reported as p50 and Max rather than a mean — a mean hides the '
          'runaway-loop tail that this measurement exists to expose.',
          style: GoogleFonts.inter(color: _muted, fontSize: 11.5),
        ),
      ],
    );
  }

  // ── Section: Cases ────────────────────────────────────────────────────────

  Widget _cases(TrajectoryReport r) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionTitle('Per-case verdicts',
            'Each query judged twice: did the answer land, and was the path legitimate?'),
        const SizedBox(height: 12),
        for (final c in r.baselineCases) _caseCard(c),
      ],
    );
  }

  Widget _caseCard(TrajectoryCaseResult c) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        color: _panel,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: c.isFalsePositive ? _red.withValues(alpha: 0.5) : _border,
        ),
      ),
      child: Theme(
        data: ThemeData.dark().copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
          iconColor: _muted,
          collapsedIconColor: _muted,
          title: Row(
            children: [
              Text(c.caseId,
                  style: GoogleFonts.robotoMono(
                      color: _indigoLight,
                      fontSize: 13,
                      fontWeight: FontWeight.w600)),
              const SizedBox(width: 10),
              _chip(c.scenarioKey, _muted, small: true),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  c.question,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: GoogleFonts.inter(color: _text, fontSize: 12.5),
                ),
              ),
              const SizedBox(width: 12),
              if (c.infraError != null)
                _chip('ERRORED', _amber, small: true)
              else ...[
                _verdictChip('outcome', c.outcomePass),
                const SizedBox(width: 6),
                _verdictChip('path', c.trajectoryPass),
              ],
              if (c.isFalsePositive) ...[
                const SizedBox(width: 8),
                _chip('FALSE POSITIVE', _red, small: true),
              ],
            ],
          ),
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _kv('Path taken',
                      c.actualPath.isEmpty ? '(no tools called)' : c.actualPath.join('  →  ')),
                  _kv(c.trajectoryPass ? 'Verdict' : 'Why it failed',
                      c.failureReason),
                  if (c.failureModes.isNotEmpty)
                    _kv('Failure modes', c.failureModes.join(', ')),
                  _kv('Steps',
                      '${c.actualSteps} taken / ${c.optimalSteps} optimal'),
                  _kv('Cost / latency',
                      '\$${c.costUsd.toStringAsFixed(6)}  ·  '
                      '${c.latencyMs.toStringAsFixed(0)} ms  ·  '
                      '${c.totalTokens} tokens'),
                  if (c.infraError != null) _kv('Infra error', c.infraError!),
                  const SizedBox(height: 8),
                  Text('Answer',
                      style: GoogleFonts.inter(
                          color: _muted,
                          fontSize: 11,
                          fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  Text(c.answer,
                      style: GoogleFonts.inter(color: _text, fontSize: 12)),
                  if (c.steps.isNotEmpty) ...[
                    const SizedBox(height: 14),
                    _stepTable(c.steps),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _stepTable(List<TrajectoryStep> steps) {
    return Container(
      decoration: BoxDecoration(
        color: _bg,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: _border),
      ),
      padding: const EdgeInsets.all(12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final s in steps) ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  s.toolChoiceOk && s.argsOk
                      ? Icons.check_circle_outline
                      : Icons.cancel_outlined,
                  size: 15,
                  color: s.toolChoiceOk && s.argsOk ? _green : _red,
                ),
                const SizedBox(width: 8),
                SizedBox(
                  width: 34,
                  child: Text('#${s.step}',
                      style: GoogleFonts.robotoMono(
                          color: _muted, fontSize: 11)),
                ),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(s.tool,
                          style: GoogleFonts.robotoMono(
                              color: _text,
                              fontSize: 12,
                              fontWeight: FontWeight.w600)),
                      if (s.toolInput != null)
                        Text(s.toolInput.toString(),
                            style: GoogleFonts.robotoMono(
                                color: _muted, fontSize: 10.5)),
                      if (!s.toolChoiceOk)
                        Text('tool choice: ${s.toolChoiceReason}',
                            style: GoogleFonts.inter(
                                color: _red, fontSize: 10.5)),
                      if (!s.argsOk)
                        Text('arguments: ${s.argsReason}',
                            style: GoogleFonts.inter(
                                color: _amber, fontSize: 10.5)),
                    ],
                  ),
                ),
              ],
            ),
            if (s != steps.last) const SizedBox(height: 10),
          ],
        ],
      ),
    );
  }

  // ── Section: False-positive trace ─────────────────────────────────────────

  Widget _trace(TrajectoryReport r) {
    final t = r.exposedTrace;
    if (t == null) {
      return _panelBox(
        child: Text(
          'No right-answer / wrong-path case in this run. Every query that '
          'produced a correct answer also took a legitimate path.',
          style: GoogleFonts.inter(color: _text, fontSize: 13),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionTitle('Exposed false positive',
            'This query passed the outcome eval and failed the trajectory eval'),
        const SizedBox(height: 12),
        _panelBox(
          borderColor: _red.withValues(alpha: 0.5),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(t.caseId,
                      style: GoogleFonts.robotoMono(
                          color: _indigoLight,
                          fontSize: 15,
                          fontWeight: FontWeight.bold)),
                  const SizedBox(width: 10),
                  _chip(t.scenarioKey, _muted, small: true),
                  const SizedBox(width: 10),
                  _chip('outcome PASS', _green, small: true),
                  const SizedBox(width: 6),
                  _chip('trajectory FAIL', _red, small: true),
                ],
              ),
              const SizedBox(height: 12),
              Text(t.question,
                  style: GoogleFonts.inter(
                      color: Colors.white,
                      fontSize: 14,
                      fontWeight: FontWeight.w600)),
              const SizedBox(height: 12),
              _kv('Why the outcome eval passed',
                  'match type "${t.outcomeMatchType}" — the answer text was accepted'),
              _kv('Why the trajectory eval failed', t.failureReason),
              _kv('Failure modes', t.failureModes.join(', ')),
              _kv('Path taken',
                  t.actualPath.isEmpty ? '(no tools called)' : t.actualPath.join('  →  ')),
              const SizedBox(height: 14),
              Text('Full execution trace',
                  style: GoogleFonts.inter(
                      color: _muted,
                      fontSize: 11,
                      fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              _stepTable(t.steps),
            ],
          ),
        ),
      ],
    );
  }

  // ── Section: Mitigation ───────────────────────────────────────────────────

  Widget _mitigation(TrajectoryReport r) {
    final m = r.mitigation;
    if (m == null) {
      return _panelBox(
        child: Text('No mitigation experiment in this report.',
            style: GoogleFonts.inter(color: _text, fontSize: 13)),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionTitle('Single mitigation experiment',
            'Exactly one fix, applied to the measured top failure mode'),
        const SizedBox(height: 12),
        _panelBox(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(m.name,
                      style: GoogleFonts.robotoMono(
                          color: _indigoLight,
                          fontSize: 15,
                          fontWeight: FontWeight.bold)),
                  const SizedBox(width: 12),
                  _chip(
                    m.wasTopMode
                        ? 'targets measured top mode ${m.measuredTopMode}'
                        : 'top mode was ${m.measuredTopMode}, not ${m.targetMode}',
                    m.wasTopMode ? _green : _amber,
                    small: true,
                  ),
                ],
              ),
              const SizedBox(height: 10),
              Text(m.description,
                  style: GoogleFonts.inter(color: _text, fontSize: 12.5)),
              const SizedBox(height: 18),
              Row(
                children: [
                  Expanded(
                    child: _statCard(
                      '${m.targetMode} · ${m.targetModeName}',
                      '${m.targetBefore} → ${m.targetAfter}',
                      '${m.targetDelta >= 0 ? '+' : ''}${m.targetDelta} failures across ${r.baseline.totalCases} queries',
                      m.targetDelta < 0 ? _green : _red,
                      emphasis: true,
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: _statCard(
                      'Gate interventions',
                      '${m.interventions}',
                      'Tool calls the guard rejected',
                      _indigoLight,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
        const SizedBox(height: 22),
        _sectionTitle('Price paid', 'The measured cost of that one fix'),
        const SizedBox(height: 12),
        _panelBox(
          child: Table(
            columnWidths: const {
              0: FlexColumnWidth(3),
              1: FlexColumnWidth(1.6),
            },
            children: [
              _tableHeader(['Resource', 'Delta']),
              _deltaRow('p50 latency',
                  _signed(m.latencyP50DeltaMs, suffix: ' ms'),
                  m.latencyP50DeltaMs),
              _deltaRow('p99 latency',
                  _signed(m.latencyP99DeltaMs, suffix: ' ms'),
                  m.latencyP99DeltaMs),
              _deltaRow('tokens / query',
                  _signed(m.tokensPerQueryDelta),
                  m.tokensPerQueryDelta),
              _deltaRow('cost / query',
                  _signed(m.costPerQueryDeltaUsd, prefix: '\$', digits: 6),
                  m.costPerQueryDeltaUsd),
              _deltaRow('cost p50',
                  _signed(m.costP50DeltaUsd, prefix: '\$', digits: 6),
                  m.costP50DeltaUsd),
              _deltaRow('total steps',
                  _signed(m.stepsDelta.toDouble(), digits: 0),
                  m.stepsDelta.toDouble()),
            ],
          ),
        ),
      ],
    );
  }

  /// Format a delta with exactly one explicit sign.
  ///
  /// The sign is prepended and the magnitude formatted from the absolute value —
  /// formatting the signed number as well would render "-280.1" as "--280.1".
  String _signed(double v, {String prefix = '', String suffix = '', int digits = 1}) {
    final sign = v < 0 ? '-' : '+';
    return '$sign$prefix${v.abs().toStringAsFixed(digits)}$suffix';
  }

  // ── Section: Regression ───────────────────────────────────────────────────

  Widget _regression(TrajectoryReport r) {
    final worsened =
        r.regressionMatrix.where((m) => m.status == 'WORSENED').toList();
    final appeared = r.regressionMatrix.where((m) => m.status == 'NEW').toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionTitle('Per-mode regression matrix',
            'Every failure mode in the taxonomy, before and after the fix'),
        const SizedBox(height: 12),
        _panelBox(
          child: Table(
            columnWidths: const {
              0: FlexColumnWidth(0.7),
              1: FlexColumnWidth(2.6),
              2: FlexColumnWidth(1),
              3: FlexColumnWidth(1),
              4: FlexColumnWidth(0.8),
              5: FlexColumnWidth(1.4),
            },
            children: [
              _tableHeader(
                  ['Code', 'Failure mode', 'Before', 'After', 'Δ', 'Status']),
              for (final m in r.regressionMatrix)
                TableRow(
                  children: [
                    _cell(m.code, mono: true),
                    _cell(m.name),
                    _cell('${m.before}'),
                    _cell('${m.after}'),
                    _cell('${m.delta >= 0 ? '+' : ''}${m.delta}'),
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 9),
                      child: Align(
                        alignment: Alignment.centerLeft,
                        child: _chip(m.status, _statusColor(m.status),
                            small: true),
                      ),
                    ),
                  ],
                ),
            ],
          ),
        ),
        const SizedBox(height: 14),
        if (appeared.isEmpty && worsened.isEmpty)
          _banner(Icons.check_circle_outline, _green,
              'No failure mode worsened and none appeared as a side effect of the fix.')
        else ...[
          if (appeared.isNotEmpty)
            _banner(
              Icons.new_releases_outlined,
              _red,
              'NEW failure modes introduced by the fix: '
              '${appeared.map((m) => '${m.code} (${m.name}) 0 → ${m.after}').join(', ')}',
            ),
          if (appeared.isNotEmpty && worsened.isNotEmpty)
            const SizedBox(height: 10),
          if (worsened.isNotEmpty)
            _banner(
              Icons.trending_up,
              _amber,
              'WORSENED failure modes: '
              '${worsened.map((m) => '${m.code} (${m.name}) ${m.before} → ${m.after}').join(', ')}',
            ),
        ],
      ],
    );
  }

  Color _statusColor(String status) => switch (status) {
        'IMPROVED' => _green,
        'WORSENED' => _amber,
        'NEW' => _red,
        _ => _muted,
      };

  // ── Section: Injection ────────────────────────────────────────────────────

  Widget _injection(TrajectoryReport r) {
    final inj = r.injection;
    if (inj == null) {
      return _panelBox(
        child: Text(
          'The injection suite was not run. Enable "Run injection suite" in '
          'the header and run again.',
          style: GoogleFonts.inter(color: _text, fontSize: 13),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionTitle('Indirect prompt injection',
            'Malicious instructions smuggled in through community comments in tool output'),
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: _statCard(
                'Attack success — undefended',
                '${inj.attackSuccessRateBefore.toStringAsFixed(0)}%',
                '${inj.undefended.length} attempts',
                _red,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: _statCard(
                'Attack success — defended',
                '${inj.attackSuccessRateAfter.toStringAsFixed(0)}%',
                '${inj.defended.length} attempts',
                inj.attackSuccessRateAfter > 0 ? _amber : _green,
                emphasis: true,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: _statCard(
                'Availability impact',
                '${inj.availabilityImpactRate.toStringAsFixed(0)}%',
                'Payload forced a refusal on an answerable query',
                inj.availabilityImpactRate > 0 ? _amber : _green,
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: _statCard(
                'Read-only tool scope',
                inj.readOnlyScopeOk ? 'VERIFIED' : 'VIOLATED',
                inj.scopeOffenders.isEmpty
                    ? 'No tool can write or call out'
                    : inj.scopeOffenders.join(', '),
                inj.readOnlyScopeOk ? _green : _red,
              ),
            ),
          ],
        ),
        if (inj.availabilityImpactRate > 0) ...[
          const SizedBox(height: 14),
          _banner(
            Icons.report_gmailerrorred_outlined,
            _amber,
            'The payloads never seized control of the output, but '
            '${inj.availabilityImpactRate.toStringAsFixed(0)}% of attempts made '
            'the agent refuse a question it answers correctly from a clean '
            'corpus. Poisoned context degrades availability even when integrity '
            'holds — a 0% hijack rate alone would have hidden this.',
          ),
        ],
        if (inj.inconclusiveAttempts > 0) ...[
          const SizedBox(height: 14),
          _banner(
            Icons.warning_amber_rounded,
            _red,
            '${inj.inconclusiveAttempts} attempt(s) aborted on provider errors '
            'and are excluded from the rates above — an outage is not a '
            'security result.',
          ),
        ],
        const SizedBox(height: 22),
        _sectionTitle('Defence penalty', 'Measured, not estimated'),
        const SizedBox(height: 12),
        _panelBox(
          child: Table(
            columnWidths: const {0: FlexColumnWidth(3), 1: FlexColumnWidth(1.6)},
            children: [
              _tableHeader(['Layer', 'Cost']),
              _pairRow('Tool-output sanitiser',
                  '${inj.sanitizeUsPerChunk.toStringAsFixed(1)} µs / chunk'),
              _pairRow('Output guardrail',
                  '${inj.guardrailUsPerAnswer.toStringAsFixed(1)} µs / answer'),
              _pairRow('Trajectory pass rate — baseline',
                  '${inj.trajectoryPassRateBaseline.toStringAsFixed(1)}%'),
              _pairRow('Trajectory pass rate — with defence',
                  '${inj.trajectoryPassRateAfterDefense.toStringAsFixed(1)}%'),
            ],
          ),
        ),
        const SizedBox(height: 22),
        _sectionTitle('Attempts', 'Each payload, undefended then defended'),
        const SizedBox(height: 12),
        for (final a in [...inj.undefended, ...inj.defended])
          Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: _panel,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: _border),
            ),
            child: Row(
              children: [
                Text(a.payloadId,
                    style: GoogleFonts.robotoMono(
                        color: _indigoLight, fontSize: 12)),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(a.label,
                      style: GoogleFonts.inter(color: _text, fontSize: 12.5)),
                ),
                if (a.becameRefusal) ...[
                  _chip('forced refusal', _amber, small: true),
                  const SizedBox(width: 8),
                ],
                if (a.guardrailBlocked) ...[
                  _chip('guardrail blocked', _green, small: true),
                  const SizedBox(width: 8),
                ],
                if (!a.conclusive)
                  _chip('INCONCLUSIVE', _red, small: true)
                else
                  _chip(a.attackSucceeded ? 'ATTACK LANDED' : 'blocked',
                      a.attackSucceeded ? _red : _green,
                      small: true),
              ],
            ),
          ),
        const SizedBox(height: 22),
        _sectionTitle('Residual vulnerabilities',
            'What this defence does NOT close'),
        const SizedBox(height: 12),
        _panelBox(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (final v in inj.residualVulnerabilities)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Padding(
                        padding: EdgeInsets.only(top: 3),
                        child: Icon(Icons.remove, size: 13, color: _amber),
                      ),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(v,
                            style: GoogleFonts.inter(
                                color: _text, fontSize: 12.5, height: 1.45)),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }

  // ── Shared building blocks ────────────────────────────────────────────────

  Widget _sectionTitle(String title, String subtitle) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: GoogleFonts.outfit(
                  color: Colors.white,
                  fontSize: 15,
                  fontWeight: FontWeight.w600)),
          const SizedBox(height: 3),
          Text(subtitle,
              style: GoogleFonts.inter(color: _muted, fontSize: 12)),
        ],
      );

  Widget _panelBox({required Widget child, Color? borderColor}) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: _panel,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: borderColor ?? _border),
        ),
        child: child,
      );

  Widget _statCard(
    String label,
    String value,
    String sub,
    Color accent, {
    bool emphasis = false,
  }) =>
      Container(
        padding: const EdgeInsets.all(18),
        decoration: BoxDecoration(
          color: emphasis ? accent.withValues(alpha: 0.10) : _panel,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: emphasis ? accent.withValues(alpha: 0.45) : _border,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label.toUpperCase(),
                style: GoogleFonts.inter(
                    color: _muted,
                    fontSize: 10.5,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.7)),
            const SizedBox(height: 10),
            Text(value,
                style: GoogleFonts.outfit(
                    color: accent,
                    fontSize: emphasis ? 30 : 26,
                    fontWeight: FontWeight.bold)),
            const SizedBox(height: 6),
            Text(sub, style: GoogleFonts.inter(color: _muted, fontSize: 11.5)),
          ],
        ),
      );

  Widget _chip(String label, Color color, {bool small = false}) => Container(
        padding: EdgeInsets.symmetric(
            horizontal: small ? 8 : 10, vertical: small ? 3 : 5),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color.withValues(alpha: 0.45)),
        ),
        child: Text(label,
            style: GoogleFonts.inter(
                color: color,
                fontSize: small ? 10 : 11,
                fontWeight: FontWeight.w600)),
      );

  Widget _verdictChip(String label, bool pass) =>
      _chip('$label ${pass ? 'PASS' : 'FAIL'}', pass ? _green : _red,
          small: true);

  Widget _banner(IconData icon, Color color, String message) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(13),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.10),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: color.withValues(alpha: 0.4)),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color, size: 17),
            const SizedBox(width: 10),
            Expanded(
              child: Text(message,
                  style: GoogleFonts.inter(
                      color: _text, fontSize: 12.5, height: 1.45)),
            ),
          ],
        ),
      );

  Widget _kv(String key, String value) => Padding(
        padding: const EdgeInsets.only(bottom: 7),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 190,
              child: Text(key,
                  style: GoogleFonts.inter(color: _muted, fontSize: 11.5)),
            ),
            Expanded(
              child: Text(value,
                  style: GoogleFonts.inter(color: _text, fontSize: 12)),
            ),
          ],
        ),
      );

  TableRow _tableHeader(List<String> labels) => TableRow(
        decoration: const BoxDecoration(
          border: Border(bottom: BorderSide(color: _border)),
        ),
        children: [
          for (final l in labels)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Text(l.toUpperCase(),
                  style: GoogleFonts.inter(
                      color: _muted,
                      fontSize: 10.5,
                      fontWeight: FontWeight.bold,
                      letterSpacing: 0.6)),
            ),
        ],
      );

  TableRow _metricRow(String label, String a, String b,
          {bool subtle = false}) =>
      TableRow(children: [
        _cell(label, color: subtle ? _muted : _text),
        _cell(a, mono: true, color: subtle ? _muted : Colors.white),
        _cell(b, mono: true, color: subtle ? _muted : Colors.white),
      ]);

  /// A two-column row. Kept separate from [_metricRow] because a Table rejects
  /// rows whose cell count differs from its header's.
  TableRow _pairRow(String label, String value) => TableRow(children: [
        _cell(label),
        _cell(value, mono: true, color: Colors.white),
      ]);

  TableRow _deltaRow(String label, String value, double delta) =>
      TableRow(children: [
        _cell(label),
        _cell(value,
            mono: true, color: delta == 0 ? _muted : (delta > 0 ? _amber : _green)),
      ]);

  Widget _cell(String text, {bool mono = false, Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 9),
        child: Text(
          text,
          style: mono
              ? GoogleFonts.robotoMono(
                  color: color ?? _text, fontSize: 12)
              : GoogleFonts.inter(color: color ?? _text, fontSize: 12.5),
        ),
      );
}
