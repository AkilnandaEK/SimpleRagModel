import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import '../models/rag_models.dart';
import '../services/api_service.dart';
import 'upload_dialog.dart';

class Sidebar extends StatelessWidget {
  final List<CollectionInfo> collections;
  final String? selectedCollection;
  final ValueChanged<String> onSelectCollection;
  final VoidCallback onRefresh;
  final bool isBackendConnected;

  const Sidebar({
    super.key,
    required this.collections,
    required this.selectedCollection,
    required this.onSelectCollection,
    required this.onRefresh,
    required this.isBackendConnected,
  });

  void _showUploadDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (context) => UploadDialog(onUploadSuccess: onRefresh),
    );
  }

  Future<void> _confirmDelete(BuildContext context, String collectionName) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF1E293B),
        title: Text(
          'Delete Collection?',
          style: GoogleFonts.outfit(color: Colors.white, fontWeight: FontWeight.bold),
        ),
        content: Text(
          'Permanently remove "$collectionName" and all its indexed chunks from ChromaDB?',
          style: GoogleFonts.inter(color: const Color(0xFFCBD5E1)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text('Cancel', style: GoogleFonts.inter(color: const Color(0xFF94A3B8))),
          ),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              backgroundColor: const Color(0xFFEF4444),
              foregroundColor: Colors.white,
            ),
            onPressed: () => Navigator.of(context).pop(true),
            child: Text('Delete', style: GoogleFonts.inter(fontWeight: FontWeight.w600)),
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
        border: Border(
          right: BorderSide(color: Color(0xFF1E293B), width: 1),
        ),
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
                      child: const Icon(Icons.auto_awesome, color: Colors.white, size: 20),
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
                                isBackendConnected ? 'FastAPI Online' : 'Offline',
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
                    onPressed: isBackendConnected ? () => _showUploadDialog(context) : null,
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
                  icon: const Icon(Icons.refresh, size: 16, color: Color(0xFF64748B)),
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
                          Icon(Icons.folder_open, size: 36, color: Colors.white.withOpacity(0.2)),
                          const SizedBox(height: 8),
                          Text(
                            'No documents indexed yet',
                            style: GoogleFonts.inter(color: const Color(0xFF64748B), fontSize: 13),
                            textAlign: TextAlign.center,
                          ),
                        ],
                      ),
                    ),
                  )
                : ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
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
                              ? Border.all(color: const Color(0xFF6366F1).withOpacity(0.5))
                              : null,
                        ),
                        child: ListTile(
                          contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 0),
                          dense: true,
                          leading: Icon(
                            Icons.description_outlined,
                            color: isSelected ? const Color(0xFF818CF8) : const Color(0xFF64748B),
                            size: 18,
                          ),
                          title: Text(
                            item.name,
                            style: GoogleFonts.inter(
                              color: isSelected ? Colors.white : const Color(0xFFCBD5E1),
                              fontSize: 13,
                              fontWeight: isSelected ? FontWeight.w600 : FontWeight.w400,
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
                                  icon: const Icon(Icons.delete_outline, size: 16, color: Color(0xFFEF4444)),
                                  onPressed: () => _confirmDelete(context, item.name),
                                  tooltip: 'Delete collection',
                                )
                              : null,
                          onTap: () => onSelectCollection(item.name),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
