import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../main.dart' show WorkspaceTab;
import '../models/rag_models.dart';
import '../services/api_service.dart';
import 'upload_dialog.dart';

class Sidebar extends StatelessWidget {
  final List<CollectionInfo> collections;
  final String? selectedCollection;
  final ValueChanged<String> onSelectCollection;
  final VoidCallback onRefresh;
  final bool isBackendConnected;
  final VoidCallback onOpenBenchmark;

  /// Runs the live Week 10 Single Agent vs Multi-Agent Squad race.
  final VoidCallback onOpenWeek10Results;

  /// True while a Week 10 race is executing, so the action can be disabled and
  /// duplicate runs prevented.
  final bool isWeek10Running;
  final WorkspaceTab activeTab;
  final ValueChanged<WorkspaceTab> onSelectTab;

  const Sidebar({
    super.key,
    required this.collections,
    required this.selectedCollection,
    required this.onSelectCollection,
    required this.onRefresh,
    required this.isBackendConnected,
    required this.onOpenBenchmark,
    required this.onOpenWeek10Results,
    required this.isWeek10Running,
    required this.activeTab,
    required this.onSelectTab,
  });

  Widget _tabButton({
    required WorkspaceTab tab,
    required IconData icon,
    required String label,
  }) {
    final active = activeTab == tab;
    return Expanded(
      child: InkWell(
        onTap: () => onSelectTab(tab),
        borderRadius: BorderRadius.circular(8),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            color: active
                ? const Color(0xFF6366F1).withValues(alpha: 0.18)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: active
                  ? const Color(0xFF6366F1).withValues(alpha: 0.6)
                  : const Color(0xFF1E293B),
            ),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                icon,
                size: 17,
                color: active
                    ? const Color(0xFF818CF8)
                    : const Color(0xFF64748B),
              ),
              const SizedBox(height: 4),
              Text(
                label,
                style: GoogleFonts.inter(
                  color: active ? Colors.white : const Color(0xFF64748B),
                  fontSize: 11.5,
                  fontWeight: active ? FontWeight.w600 : FontWeight.w400,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _showUploadDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (context) => UploadDialog(onUploadSuccess: onRefresh),
    );
  }

  Future<void> _confirmDelete(
    BuildContext context,
    String collectionName,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1E293B),
        title: Text(
          'Delete Collection?',
          style: GoogleFonts.outfit(
            color: Colors.white,
            fontWeight: FontWeight.bold,
          ),
        ),
        content: Text(
          'Permanently remove "$collectionName" and all its indexed chunks from ChromaDB?',
          style: GoogleFonts.inter(color: const Color(0xFFCBD5E1)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(
              'Cancel',
              style: GoogleFonts.inter(color: const Color(0xFF94A3B8)),
            ),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFEF4444),
              foregroundColor: Colors.white,
            ),
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(
              'Delete',
              style: GoogleFonts.inter(fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );

    if (confirmed == true) {
      final success = await ApiService.deleteCollection(collectionName);
      if (success) {
        onRefresh();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 280,
      decoration: const BoxDecoration(
        color: Color(0xFF0F172A),
        border: Border(right: BorderSide(color: Color(0xFF1E293B), width: 1)),
      ),
      child: Column(
        children: [
          // Header
          Container(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      padding: const EdgeInsets.all(8),
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(
                          colors: [Color(0xFF6366F1), Color(0xFF8B5CF6)],
                        ),
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: const Icon(
                        Icons.auto_awesome,
                        color: Colors.white,
                        size: 20,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            'RAG Hub',
                            style: GoogleFonts.outfit(
                              color: Colors.white,
                              fontSize: 18,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          Row(
                            children: [
                              Container(
                                width: 8,
                                height: 8,
                                decoration: BoxDecoration(
                                  shape: BoxShape.circle,
                                  color: isBackendConnected
                                      ? const Color(0xFF10B981)
                                      : const Color(0xFFEF4444),
                                ),
                              ),
                              const SizedBox(width: 6),
                              Text(
                                isBackendConnected
                                    ? 'FastAPI Online'
                                    : 'Offline',
                                style: GoogleFonts.inter(
                                  color: isBackendConnected
                                      ? const Color(0xFF10B981)
                                      : const Color(0xFFEF4444),
                                  fontSize: 11,
                                  fontWeight: FontWeight.w500,
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 20),

                // Upload Button
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: isBackendConnected
                        ? () => _showUploadDialog(context)
                        : null,
                    icon: const Icon(Icons.add, size: 18),
                    label: Text(
                      'Upload PDF',
                      style: GoogleFonts.inter(fontWeight: FontWeight.w600),
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF6366F1),
                      foregroundColor: Colors.white,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                      elevation: 0,
                    ),
                  ),
                ),
              ],
            ),
          ),

          const Divider(height: 1, color: Color(0xFF1E293B)),

          // Workspace tabs
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 14, 16, 4),
            child: Row(
              children: [
                _tabButton(
                  tab: WorkspaceTab.chat,
                  icon: Icons.forum_outlined,
                  label: 'Chat',
                ),
                const SizedBox(width: 8),
                _tabButton(
                  tab: WorkspaceTab.evals,
                  icon: Icons.route_outlined,
                  label: 'Evals',
                ),
              ],
            ),
          ),

          const SizedBox(height: 6),
          const Divider(height: 1, color: Color(0xFF1E293B)),

          // Section Title
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  'DOCUMENT COLLECTIONS',
                  style: GoogleFonts.inter(
                    color: const Color(0xFF64748B),
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.8,
                  ),
                ),
                IconButton(
                  icon: const Icon(
                    Icons.refresh,
                    size: 16,
                    color: Color(0xFF64748B),
                  ),
                  onPressed: onRefresh,
                  tooltip: 'Refresh collections',
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(),
                ),
              ],
            ),
          ),

          // Collections List
          Expanded(
            child: collections.isEmpty
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(20),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            Icons.folder_open,
                            size: 36,
                            color: Colors.white.withOpacity(0.2),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'No documents indexed yet',
                            style: GoogleFonts.inter(
                              color: const Color(0xFF64748B),
                              fontSize: 13,
                            ),
                            textAlign: TextAlign.center,
                          ),
                        ],
                      ),
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 4,
                    ),
                    itemCount: collections.length,
                    itemBuilder: (context, index) {
                      final item = collections[index];
                      final isSelected = item.name == selectedCollection;

                      return Container(
                        margin: const EdgeInsets.only(bottom: 4),
                        decoration: BoxDecoration(
                          color: isSelected
                              ? const Color(0xFF1E293B)
                              : Colors.transparent,
                          borderRadius: BorderRadius.circular(8),
                          border: isSelected
                              ? Border.all(
                                  color: const Color(
                                    0xFF6366F1,
                                  ).withOpacity(0.5),
                                )
                              : null,
                        ),
                        child: ListTile(
                          contentPadding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 0,
                          ),
                          dense: true,
                          leading: Icon(
                            Icons.description_outlined,
                            color: isSelected
                                ? const Color(0xFF818CF8)
                                : const Color(0xFF64748B),
                            size: 18,
                          ),
                          title: Text(
                            item.name,
                            style: GoogleFonts.inter(
                              color: isSelected
                                  ? Colors.white
                                  : const Color(0xFFCBD5E1),
                              fontSize: 13,
                              fontWeight: isSelected
                                  ? FontWeight.w600
                                  : FontWeight.w400,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          subtitle: Text(
                            '${item.count} chunks',
                            style: GoogleFonts.inter(
                              color: const Color(0xFF64748B),
                              fontSize: 11,
                            ),
                          ),
                          trailing: isSelected
                              ? IconButton(
                                  icon: const Icon(
                                    Icons.delete_outline,
                                    size: 16,
                                    color: Color(0xFFEF4444),
                                  ),
                                  onPressed: () =>
                                      _confirmDelete(context, item.name),
                                  tooltip: 'Delete collection',
                                )
                              : null,
                          onTap: () => onSelectCollection(item.name),
                        ),
                      );
                    },
                  ),
          ),

          // Evaluation footer
          const Divider(height: 1, color: Color(0xFF1E293B)),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 14, 20, 14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'EVALUATION LAB',
                  style: GoogleFonts.inter(
                    color: const Color(0xFF64748B),
                    fontSize: 11,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.8,
                  ),
                ),
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: onOpenBenchmark,
                    icon: const Icon(
                      Icons.bar_chart_rounded,
                      size: 16,
                      color: Color(0xFF818CF8),
                    ),
                    label: Text(
                      'Agent vs Workflow Benchmark',
                      style: GoogleFonts.inter(
                        color: const Color(0xFFCBD5E1),
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                      ),
                      textAlign: TextAlign.center,
                    ),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: const Color(0xFFCBD5E1),
                      side: const BorderSide(color: Color(0xFF334155)),
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                // Week 10 — genuinely executes the Single Agent vs
                // Multi-Agent Squad race through POST
                // /api/benchmark/week10/race.
                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton(
                    onPressed: isWeek10Running ? null : onOpenWeek10Results,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: const Color(0xFFCBD5E1),
                      disabledForegroundColor: const Color(0xFF64748B),
                      side: const BorderSide(color: Color(0xFF334155)),
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                    // Built as an explicit Row + Flexible rather than
                    // OutlinedButton.icon: this label is longer than the
                    // sidebar is wide, so it has to be allowed to wrap instead
                    // of overflowing.
                    child: Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        if (isWeek10Running) ...[
                          const SizedBox(
                            width: 13,
                            height: 13,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Color(0xFFFBBF24),
                            ),
                          ),
                        ] else ...[
                          const Icon(
                            Icons.hub_outlined,
                            size: 16,
                            color: Color(0xFFFBBF24),
                          ),
                        ],
                        const SizedBox(width: 8),
                        Flexible(
                          child: Text(
                            'Run Agent vs Multi-Agent Benchmark',
                            style: GoogleFonts.inter(
                              color: isWeek10Running
                                  ? const Color(0xFF64748B)
                                  : const Color(0xFFCBD5E1),
                              fontSize: 12.5,
                              fontWeight: FontWeight.w500,
                            ),
                            textAlign: TextAlign.center,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
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
}
