import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../models/rag_models.dart';
import '../services/api_service.dart';

/// Dialog showing the golden set and its MRR@k, split by dev / test.
///
/// Open with [showMrrDialog]. Refetches whenever the split filter or k changes.
///
/// The evaluated collection comes from the golden set itself, NOT from
/// [selectedCollection] — a golden set's expected chunk IDs encode the source
/// filename and chunk index, so scoring it against another corpus yields 0.0 on
/// every query. [selectedCollection] is used only to warn about that mismatch.
class MrrView extends StatefulWidget {
  final String? selectedCollection;

  const MrrView({super.key, required this.selectedCollection});

  @override
  State<MrrView> createState() => _MrrViewState();
}

class _MrrViewState extends State<MrrView> {
  static const _splitOptions = <String?>[null, 'dev', 'test'];

  String? _split;
  int _topK = 0;
  late Future<MrrReport> _future;

  @override
  void initState() {
    super.initState();
    _future = _load();
  }

  Future<MrrReport> _load() {
    // collectionName intentionally omitted — the backend resolves it from the
    // golden set's own 'collection_name'.
    return ApiService.fetchMrrReport(topK: _topK, split: _split);
  }

  void _reload() {
    setState(() => _future = _load());
  }

  Color _rrColor(double rr) {
    if (rr >= 1.0) return const Color(0xFF10B981);
    if (rr >= 0.5) return const Color(0xFFFBBF24);
    if (rr > 0.0) return const Color(0xFFF97316);
    return const Color(0xFFEF4444);
  }

  Color _splitColor(String split) =>
      split == 'dev' ? const Color(0xFF38BDF8) : const Color(0xFFA78BFA);

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: const Color(0xFF0F172A),
      surfaceTintColor: Colors.transparent,
      insetPadding: const EdgeInsets.all(24),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      title: Row(
        children: [
          const Icon(Icons.leaderboard_outlined, color: Color(0xFF818CF8)),
          const SizedBox(width: 10),
          Text(
            'Retrieval Evaluation — MRR',
            style: GoogleFonts.outfit(
              color: Colors.white,
              fontWeight: FontWeight.bold,
            ),
          ),
          const Spacer(),
          _buildControls(),
        ],
      ),
      content: SizedBox(
        width: 1000,
        height: 620,
        child: FutureBuilder<MrrReport>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const Center(
                child: CircularProgressIndicator(color: Color(0xFF6366F1)),
              );
            }
            if (snapshot.hasError) {
              return _buildError(snapshot.error.toString());
            }
            final report = snapshot.data;
            if (report == null || report.evaluations.isEmpty) {
              return Center(
                child: Text(
                  'No graded queries returned.',
                  style: GoogleFonts.inter(color: const Color(0xFFCBD5E1)),
                ),
              );
            }
            return SingleChildScrollView(child: _buildBody(report));
          },
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: Text(
            'Close',
            style: GoogleFonts.inter(color: const Color(0xFF818CF8)),
          ),
        ),
      ],
    );
  }

  Widget _buildControls() {
    return Row(
      children: [
        Text(
          'Split',
          style: GoogleFonts.inter(
            color: const Color(0xFF94A3B8),
            fontSize: 12,
          ),
        ),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10),
          decoration: BoxDecoration(
            color: const Color(0xFF1E293B),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: const Color(0xFF334155)),
          ),
          child: DropdownButton<String?>(
            value: _split,
            underline: const SizedBox.shrink(),
            dropdownColor: const Color(0xFF1E293B),
            style: GoogleFonts.inter(color: Colors.white, fontSize: 12),
            items: _splitOptions
                .map(
                  (value) => DropdownMenuItem<String?>(
                    value: value,
                    child: Text(value ?? 'all'),
                  ),
                )
                .toList(),
            onChanged: (value) {
              _split = value;
              _reload();
            },
          ),
        ),
        const SizedBox(width: 14),
        Text(
          'top_k',
          style: GoogleFonts.inter(
            color: const Color(0xFF94A3B8),
            fontSize: 12,
          ),
        ),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10),
          decoration: BoxDecoration(
            color: const Color(0xFF1E293B),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: const Color(0xFF334155)),
          ),
          child: DropdownButton<int>(
            value: _topK,
            underline: const SizedBox.shrink(),
            dropdownColor: const Color(0xFF1E293B),
            style: GoogleFonts.inter(color: Colors.white, fontSize: 12),
            items: const [0, 1, 3, 5, 10]
                .map(
                  (value) => DropdownMenuItem<int>(
                    value: value,
                    child: Text(value == 0 ? 'default' : '$value'),
                  ),
                )
                .toList(),
            onChanged: (value) {
              if (value == null) return;
              _topK = value;
              _reload();
            },
          ),
        ),
        const SizedBox(width: 8),
        IconButton(
          tooltip: 'Re-run evaluation',
          onPressed: _reload,
          icon: const Icon(Icons.refresh, size: 18, color: Color(0xFF818CF8)),
        ),
      ],
    );
  }

  Widget _buildError(String message) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.error_outline, color: Color(0xFFFCA5A5), size: 36),
          const SizedBox(height: 12),
          Text(
            message,
            textAlign: TextAlign.center,
            style: GoogleFonts.inter(
              color: const Color(0xFFFCA5A5),
              fontSize: 13,
            ),
          ),
          const SizedBox(height: 14),
          TextButton.icon(
            onPressed: _reload,
            icon: const Icon(Icons.refresh, size: 16),
            label: const Text('Retry'),
          ),
        ],
      ),
    );
  }

  Widget _buildBody(MrrReport report) {
    final dev = report.scoreFor('dev');
    final test = report.scoreFor('test');
    final misses = report.evaluations.where((e) => !e.isHit).toList();

    final selected = widget.selectedCollection;
    final mismatched = selected != null && selected != report.collectionName;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (mismatched)
          _buildBanner(
            icon: Icons.info_outline,
            color: const Color(0xFF38BDF8),
            message:
                'Scored against "${report.collectionName}" — the corpus this '
                'golden set was written for. Your selected collection '
                '"$selected" is not evaluated, because expected chunk IDs are '
                'specific to a corpus and its chunking.',
          ),
        for (final warning in report.warnings)
          _buildBanner(
            icon: Icons.warning_amber_rounded,
            color: const Color(0xFFFBBF24),
            message: warning,
          ),
        Row(
          children: [
            Expanded(
              child: _buildScoreCard(
                title: 'MRR@${report.topK} — overall',
                score: report.mrr.toStringAsFixed(4),
                subtitle: '${report.queryCount} queries',
                color: const Color(0xFF6366F1),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _buildScoreCard(
                title: 'dev split',
                score: dev == null ? '—' : dev.mrr.toStringAsFixed(4),
                subtitle: dev == null
                    ? 'not in this run'
                    : '${dev.queryCount} queries · tune here',
                color: const Color(0xFF38BDF8),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: _buildScoreCard(
                title: 'test split',
                score: test == null ? '—' : test.mrr.toStringAsFixed(4),
                subtitle: test == null
                    ? 'not in this run'
                    : '${test.queryCount} queries · held out',
                color: const Color(0xFFA78BFA),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Text(
          'Collection: ${report.collectionName}   ·   '
          'Split filter: ${report.split ?? 'all'}   ·   '
          'RR = 1 / rank of the first relevant chunk (0 if it never appears)',
          style: GoogleFonts.inter(
            color: const Color(0xFF64748B),
            fontSize: 11,
          ),
        ),
        const SizedBox(height: 16),
        _buildSection('Golden Set — per-query reciprocal rank', _buildTable(report)),
        if (misses.isNotEmpty) ...[
          const SizedBox(height: 14),
          _buildSection(
            'Missed queries (${misses.length}) — nothing relevant in the top ${report.topK}',
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: misses.map(_buildMissCard).toList(),
            ),
          ),
        ],
      ],
    );
  }

  Widget _buildBanner({
    required IconData icon,
    required Color color,
    required String message,
  }) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.45)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 16, color: color),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              message,
              style: GoogleFonts.inter(color: color, fontSize: 11.5, height: 1.4),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildScoreCard({
    required String title,
    required String score,
    required String subtitle,
    required Color color,
  }) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: GoogleFonts.inter(
              color: const Color(0xFF94A3B8),
              fontSize: 12,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            score,
            style: GoogleFonts.outfit(
              color: color,
              fontSize: 26,
              fontWeight: FontWeight.bold,
            ),
          ),
          Text(
            subtitle,
            style: GoogleFonts.inter(color: Colors.white70, fontSize: 11),
          ),
        ],
      ),
    );
  }

  Widget _buildSection(String title, Widget child) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
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
            style: GoogleFonts.outfit(
              color: Colors.white,
              fontSize: 15,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 10),
          child,
        ],
      ),
    );
  }

  Widget _buildTable(MrrReport report) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowColor: WidgetStateProperty.all(const Color(0xFF1E293B)),
        dataRowColor: WidgetStateProperty.all(const Color(0xFF0F172A)),
        dividerThickness: 0.6,
        columnSpacing: 22,
        columns: const ['QID', 'Split', 'Question', 'Expected', 'Rank', 'RR']
            .map(
              (header) => DataColumn(
                label: Text(
                  header,
                  style: TextStyle(
                    color: const Color(0xFFA5B4FC),
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
            )
            .toList(),
        rows: report.evaluations.map((item) {
          return DataRow(
            cells: [
              DataCell(
                Text(
                  item.id,
                  style: GoogleFonts.inter(
                    color: const Color(0xFF818CF8),
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
              DataCell(_buildSplitBadge(item.split)),
              DataCell(
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 300),
                  child: Text(
                    item.question,
                    style: GoogleFonts.inter(color: Colors.white, fontSize: 11),
                  ),
                ),
              ),
              DataCell(
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 220),
                  child: Text(
                    item.expectedChunkIds.join(', '),
                    style: GoogleFonts.inter(
                      color: const Color(0xFFCBD5E1),
                      fontSize: 10,
                    ),
                  ),
                ),
              ),
              DataCell(
                Text(
                  item.firstRelevantRank?.toString() ?? '—',
                  style: GoogleFonts.inter(
                    color: item.isHit
                        ? Colors.white
                        : const Color(0xFFFCA5A5),
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              DataCell(
                Text(
                  item.reciprocalRank.toStringAsFixed(4),
                  style: GoogleFonts.inter(
                    color: _rrColor(item.reciprocalRank),
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          );
        }).toList(),
      ),
    );
  }

  Widget _buildSplitBadge(String split) {
    final color = _splitColor(split);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        split,
        style: GoogleFonts.inter(
          color: color,
          fontSize: 10,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }

  Widget _buildMissCard(MrrQueryEvaluation item) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                item.id,
                style: GoogleFonts.inter(
                  color: const Color(0xFF818CF8),
                  fontSize: 12,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(width: 8),
              _buildSplitBadge(item.split),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            item.question,
            style: GoogleFonts.inter(color: Colors.white, fontSize: 12),
          ),
          const SizedBox(height: 6),
          Text(
            'Expected: ${item.expectedChunkIds.join(', ')}',
            style: GoogleFonts.inter(
              color: const Color(0xFF6EE7B7),
              fontSize: 11,
            ),
          ),
          const SizedBox(height: 2),
          Text(
            'Retrieved: ${item.retrievedChunkIds.join(', ')}',
            style: GoogleFonts.inter(
              color: const Color(0xFFFCA5A5),
              fontSize: 11,
            ),
          ),
        ],
      ),
    );
  }
}

/// Convenience opener so callers don't need to import [MrrView] internals.
///
/// [selectedCollection] is only used to warn when the user's selected collection
/// differs from the one the golden set is scored against.
Future<void> showMrrDialog(BuildContext context, String? selectedCollection) {
  return showDialog(
    context: context,
    builder: (_) => MrrView(selectedCollection: selectedCollection),
  );
}
