import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';
import '../models/rag_models.dart';
import 'mrr_view.dart';

class ChatView extends StatefulWidget {
  final String? selectedCollection;
  final bool debugMode;
  final ValueChanged<bool> onDebugModeChanged;
  final List<ChatMessage> messages;
  final Future<void> Function(String question) onSendQuestion;

  const ChatView({
    super.key,
    required this.selectedCollection,
    required this.debugMode,
    required this.onDebugModeChanged,
    required this.messages,
    required this.onSendQuestion,
  });

  @override
  State<ChatView> createState() => _ChatViewState();
}

class _ChatViewState extends State<ChatView> {
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  bool _isSending = false;

  void _submit() async {
    final text = _inputController.text.trim();
    if (text.isEmpty || widget.selectedCollection == null || _isSending) return;

    _inputController.clear();
    setState(() => _isSending = true);

    await widget.onSendQuestion(text);

    setState(() => _isSending = false);
    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    if (widget.selectedCollection == null) {
      return Container(
        color: const Color(0xFF0B0F19),
        child: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                padding: const EdgeInsets.all(20),
                decoration: BoxDecoration(
                  color: const Color(0xFF1E293B),
                  shape: BoxShape.circle,
                  border: Border.all(color: const Color(0xFF334155)),
                ),
                child: const Icon(
                  Icons.picture_as_pdf_outlined,
                  size: 48,
                  color: Color(0xFF818CF8),
                ),
              ),
              const SizedBox(height: 16),
              Text(
                'Select or Upload a Document',
                style: GoogleFonts.outfit(
                  color: Colors.white,
                  fontSize: 22,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'Choose an indexed collection from the left sidebar to start querying with Gemini',
                style: GoogleFonts.inter(
                  color: const Color(0xFF94A3B8),
                  fontSize: 14,
                ),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      );
    }

    return Container(
      color: const Color(0xFF0B0F19),
      child: Column(
        children: [
          // Header Bar with chunking method and debug controls
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
            decoration: const BoxDecoration(
              color: Color(0xFF0F172A),
              border: Border(bottom: BorderSide(color: Color(0xFF1E293B))),
            ),
            child: Row(
              children: [
                const Icon(
                  Icons.folder_special,
                  color: Color(0xFF818CF8),
                  size: 20,
                ),
                const SizedBox(width: 10),
                Text(
                  widget.selectedCollection!,
                  style: GoogleFonts.outfit(
                    color: Colors.white,
                    fontSize: 15,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(width: 16),

                // Single context-aware chunking method
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 8,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFF1E293B),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: const Color(0xFF334155)),
                  ),
                  child: Text(
                    'Chunking: Context-Aware',
                    style: GoogleFonts.inter(color: Colors.white, fontSize: 12),
                  ),
                ),
                const Spacer(),

                // RAG Debug Toggle Switch
                Row(
                  children: [
                    Text(
                      'RAG Debug',
                      style: GoogleFonts.inter(
                        color: const Color(0xFF94A3B8),
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    Switch(
                      value: widget.debugMode,
                      activeThumbColor: const Color(0xFF6366F1),
                      onChanged: widget.onDebugModeChanged,
                    ),
                  ],
                ),
                const SizedBox(width: 12),

                // Golden set / MRR evaluation
                TextButton.icon(
                  onPressed: () =>
                      showMrrDialog(context, widget.selectedCollection),
                  icon: const Icon(
                    Icons.leaderboard_outlined,
                    size: 16,
                    color: Color(0xFF818CF8),
                  ),
                  label: Text(
                    'MRR',
                    style: GoogleFonts.inter(
                      color: const Color(0xFF818CF8),
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  style: TextButton.styleFrom(
                    backgroundColor: const Color(0xFF1E293B),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 12,
                    ),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                      side: const BorderSide(color: Color(0xFF334155)),
                    ),
                  ),
                ),
              ],
            ),
          ),

          // Message Stream
          Expanded(
            child: widget.messages.isEmpty
                ? Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(
                          Icons.chat_bubble_outline,
                          size: 44,
                          color: Colors.white.withValues(alpha: 0.15),
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'Ask any question about "${widget.selectedCollection}"',
                          style: GoogleFonts.inter(
                            color: const Color(0xFF64748B),
                            fontSize: 14,
                          ),
                        ),
                      ],
                    ),
                  )
                : ListView.builder(
                    controller: _scrollController,
                    padding: const EdgeInsets.all(24),
                    itemCount: widget.messages.length,
                    itemBuilder: (context, index) {
                      final msg = widget.messages[index];
                      return _buildMessageBubble(msg);
                    },
                  ),
          ),

          // Input Area
          Container(
            padding: const EdgeInsets.all(20),
            decoration: const BoxDecoration(
              color: Color(0xFF0F172A),
              border: Border(top: BorderSide(color: Color(0xFF1E293B))),
            ),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _inputController,
                    enabled: !_isSending,
                    style: GoogleFonts.inter(color: Colors.white),
                    onSubmitted: (_) => _submit(),
                    decoration: InputDecoration(
                      hintText:
                          'Ask a question about ${widget.selectedCollection}…',
                      hintStyle: GoogleFonts.inter(
                        color: const Color(0xFF64748B),
                      ),
                      filled: true,
                      fillColor: const Color(0xFF1E293B),
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 20,
                        vertical: 16,
                      ),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: BorderSide.none,
                      ),
                      focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(12),
                        borderSide: const BorderSide(color: Color(0xFF6366F1)),
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                SizedBox(
                  height: 52,
                  width: 52,
                  child: ElevatedButton(
                    onPressed: _isSending ? null : _submit,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFF6366F1),
                      foregroundColor: Colors.white,
                      padding: EdgeInsets.zero,
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                      ),
                      elevation: 0,
                    ),
                    child: _isSending
                        ? const SizedBox(
                            width: 20,
                            height: 20,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.send_rounded, size: 20),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMessageBubble(ChatMessage msg) {
    final isUser = msg.sender == 'user';

    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: isUser
            ? MainAxisAlignment.end
            : MainAxisAlignment.start,
        children: [
          if (!isUser) ...[
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
                size: 16,
              ),
            ),
            const SizedBox(width: 12),
          ],
          Flexible(
            child: Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: isUser
                    ? const Color(0xFF6366F1)
                    : const Color(0xFF1E293B),
                borderRadius: BorderRadius.circular(14),
                border: isUser
                    ? null
                    : Border.all(color: const Color(0xFF334155)),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (msg.isLoading)
                    Row(
                      children: [
                        const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Color(0xFF818CF8),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Text(
                          'Searching ChromaDB & generating answer with Gemini…',
                          style: GoogleFonts.inter(
                            color: const Color(0xFF94A3B8),
                            fontSize: 13,
                          ),
                        ),
                      ],
                    )
                  else
                    SelectableText(
                      msg.text,
                      style: GoogleFonts.inter(
                        color: Colors.white,
                        fontSize: 14,
                        height: 1.5,
                      ),
                    ),

                  // Standard Sources Accordion
                  if (msg.sources != null && msg.sources!.isNotEmpty) ...[
                    const SizedBox(height: 14),
                    const Divider(color: Color(0xFF334155), height: 1),
                    const SizedBox(height: 10),
                    Theme(
                      data: Theme.of(
                        context,
                      ).copyWith(dividerColor: Colors.transparent),
                      child: ExpansionTile(
                        tilePadding: EdgeInsets.zero,
                        childrenPadding: EdgeInsets.zero,
                        title: Row(
                          children: [
                            const Icon(
                              Icons.menu_book,
                              size: 15,
                              color: Color(0xFF818CF8),
                            ),
                            const SizedBox(width: 8),
                            Text(
                              'Retrieved Sources (${msg.sources!.length} chunks)',
                              style: GoogleFonts.inter(
                                color: const Color(0xFF818CF8),
                                fontSize: 12,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                        children: msg.sources!.map((s) {
                          return Container(
                            margin: const EdgeInsets.only(top: 8),
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: const Color(0xFF0F172A),
                              borderRadius: BorderRadius.circular(8),
                              border: Border.all(
                                color: const Color(0xFF334155),
                              ),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  mainAxisAlignment:
                                      MainAxisAlignment.spaceBetween,
                                  children: [
                                    Text(
                                      s.chunkId,
                                      style: GoogleFonts.inter(
                                        color: const Color(0xFF94A3B8),
                                        fontSize: 11,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 6,
                                        vertical: 2,
                                      ),
                                      decoration: BoxDecoration(
                                        color: const Color(
                                          0xFF10B981,
                                        ).withValues(alpha: 0.15),
                                        borderRadius: BorderRadius.circular(4),
                                      ),
                                      child: Text(
                                        'Cosine Dist: ${s.distance.toStringAsFixed(4)}',
                                        style: GoogleFonts.inter(
                                          color: const Color(0xFF10B981),
                                          fontSize: 10,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 6),
                                Text(
                                  s.text,
                                  style: GoogleFonts.inter(
                                    color: const Color(0xFFCBD5E1),
                                    fontSize: 12,
                                    height: 1.4,
                                  ),
                                ),
                              ],
                            ),
                          );
                        }).toList(),
                      ),
                    ),
                  ],

                  // RAG Evaluation / Debug Expandable View
                  if (msg.evaluation != null) ...[
                    const SizedBox(height: 12),
                    _buildEvaluationAccordion(msg.evaluation!),
                  ],
                ],
              ),
            ),
          ),
          if (isUser) ...[
            const SizedBox(width: 12),
            CircleAvatar(
              radius: 16,
              backgroundColor: const Color(0xFF334155),
              child: const Icon(Icons.person, color: Colors.white, size: 18),
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildEvaluationAccordion(EvaluationDetails eval) {
    return Container(
      margin: const EdgeInsets.only(top: 8),
      decoration: BoxDecoration(
        color: const Color(0xFF090D16),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFF6366F1).withValues(alpha: 0.4)),
      ),
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
          childrenPadding: const EdgeInsets.all(14),
          title: Row(
            children: [
              const Icon(Icons.bug_report, size: 16, color: Color(0xFFA5B4FC)),
              const SizedBox(width: 8),
              Text(
                'Show RAG Evaluation / Debug Details',
                style: GoogleFonts.inter(
                  color: const Color(0xFFA5B4FC),
                  fontSize: 13,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: eval.responseStatus == 'refused'
                      ? Colors.amber.withValues(alpha: 0.2)
                      : Colors.green.withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(4),
                ),
                child: Text(
                  eval.responseStatus.toUpperCase(),
                  style: GoogleFonts.inter(
                    color: eval.responseStatus == 'refused'
                        ? Colors.amber
                        : Colors.greenAccent,
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          ),
          children: [
            // A. Query Information
            _buildEvalSectionHeader('A. Query Configuration'),
            _buildQueryConfigCard(eval),
            const SizedBox(height: 14),

            // B. Retrieved Chunks
            _buildEvalSectionHeader(
              'B. Retrieved Chunks (${eval.retrievedChunks.length} chunks)',
            ),
            ...eval.retrievedChunks.map((c) => _buildRetrievedChunkCard(c)),
            const SizedBox(height: 14),

            // C. Retrieved Context
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                _buildEvalSectionHeader('C. Retrieved Context Sent to LLM'),
                TextButton.icon(
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: eval.context));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Context copied to clipboard!'),
                      ),
                    );
                  },
                  icon: const Icon(
                    Icons.copy,
                    size: 14,
                    color: Color(0xFF818CF8),
                  ),
                  label: Text(
                    'Copy Context',
                    style: GoogleFonts.inter(
                      color: const Color(0xFF818CF8),
                      fontSize: 11,
                    ),
                  ),
                ),
              ],
            ),
            _buildPreformattedBox(eval.context),
            const SizedBox(height: 14),

            // D. Exact LLM Prompt
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                _buildEvalSectionHeader('D. Exact Prompt Sent to Gemini'),
                TextButton.icon(
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: eval.llmPrompt));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Prompt copied to clipboard!'),
                      ),
                    );
                  },
                  icon: const Icon(
                    Icons.copy,
                    size: 14,
                    color: Color(0xFF818CF8),
                  ),
                  label: Text(
                    'Copy Prompt',
                    style: GoogleFonts.inter(
                      color: const Color(0xFF818CF8),
                      fontSize: 11,
                    ),
                  ),
                ),
              ],
            ),
            _buildPreformattedBox(eval.llmPrompt),
            const SizedBox(height: 14),

            // E. LLM Response & Status
            _buildEvalSectionHeader('E. LLM Response & Status'),
            Container(
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
                        'Status: ',
                        style: GoogleFonts.inter(
                          color: const Color(0xFF94A3B8),
                          fontSize: 12,
                        ),
                      ),
                      Text(
                        eval.responseStatus == 'refused'
                            ? 'Refused (Out-of-corpus)'
                            : 'Answered',
                        style: GoogleFonts.inter(
                          color: eval.responseStatus == 'refused'
                              ? Colors.amber
                              : Colors.greenAccent,
                          fontWeight: FontWeight.bold,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    eval.answer,
                    style: GoogleFonts.inter(color: Colors.white, fontSize: 13),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),

            // F. Citations
            _buildEvalSectionHeader('F. Citations (${eval.citations.length})'),
            ...eval.citations.map((cit) {
              return Container(
                margin: const EdgeInsets.only(bottom: 6),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: const Color(0xFF1E293B),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: const Color(0xFF334155)),
                ),
                child: Row(
                  children: [
                    const Icon(
                      Icons.bookmark_outline,
                      size: 14,
                      color: Color(0xFF818CF8),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      cit.chunkId,
                      style: GoogleFonts.inter(
                        color: const Color(0xFF818CF8),
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Text(
                      'Page: ${cit.pageId ?? "1"}',
                      style: GoogleFonts.inter(
                        color: const Color(0xFF94A3B8),
                        fontSize: 11,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Text(
                      'Anchor: ${cit.anchor ?? "#"}',
                      style: GoogleFonts.inter(
                        color: const Color(0xFF38BDF8),
                        fontSize: 11,
                      ),
                    ),
                  ],
                ),
              );
            }),
          ],
        ),
      ),
    );
  }

  Widget _buildEvalSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text(
        title,
        style: GoogleFonts.outfit(
          color: const Color(0xFFCBD5E1),
          fontSize: 13,
          fontWeight: FontWeight.bold,
        ),
      ),
    );
  }

  Widget _buildQueryConfigCard(EvaluationDetails eval) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF1E293B),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildInfoRow('Question', eval.query),
          _buildInfoRow('Collection', eval.collectionName),
          _buildInfoRow('Strategy', eval.chunkingStrategy),
          _buildInfoRow('Top K', eval.topK.toString()),
          _buildInfoRow(
            'Filter',
            eval.metadataFilter != null
                ? eval.metadataFilter.toString()
                : 'None',
          ),
        ],
      ),
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 90,
            child: Text(
              '$label:',
              style: GoogleFonts.inter(
                color: const Color(0xFF94A3B8),
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: GoogleFonts.inter(color: Colors.white, fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildRetrievedChunkCard(EvaluationChunk c) {
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
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Rank #${c.rank} • ${c.chunkId}',
                style: GoogleFonts.inter(
                  color: const Color(0xFF818CF8),
                  fontSize: 12,
                  fontWeight: FontWeight.bold,
                ),
              ),
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 6,
                      vertical: 2,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0xFF10B981).withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      'Dist: ${c.distance.toStringAsFixed(4)}',
                      style: GoogleFonts.inter(
                        color: const Color(0xFF10B981),
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                  if (c.similarityScore != null) ...[
                    const SizedBox(width: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 6,
                        vertical: 2,
                      ),
                      decoration: BoxDecoration(
                        color: const Color(0xFF38BDF8).withValues(alpha: 0.15),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        'Sim: ${(c.similarityScore! * 100).toStringAsFixed(1)}%',
                        style: GoogleFonts.inter(
                          color: const Color(0xFF38BDF8),
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'Metadata: file=${c.sourceFile ?? "doc"}, page=${c.pageId ?? "1"}, section=${c.section ?? "N/A"}, anchor=${c.anchor ?? "#"}',
            style: GoogleFonts.inter(
              color: const Color(0xFF94A3B8),
              fontSize: 11,
            ),
          ),
          const SizedBox(height: 8),
          Theme(
            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              title: Text(
                'Show Chunk Text',
                style: GoogleFonts.inter(
                  color: const Color(0xFF38BDF8),
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                ),
              ),
              children: [
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: const Color(0xFF0F172A),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: SelectableText(
                    c.text,
                    style: GoogleFonts.inter(
                      color: const Color(0xFFCBD5E1),
                      fontSize: 12,
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

  Widget _buildPreformattedBox(String text) {
    return Container(
      width: double.infinity,
      constraints: const BoxConstraints(maxHeight: 220),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: const Color(0xFF0F172A),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFF334155)),
      ),
      child: SingleChildScrollView(
        child: SelectableText(
          text,
          style: GoogleFonts.firaCode(
            color: const Color(0xFF94A3B8),
            fontSize: 11,
            height: 1.4,
          ),
        ),
      ),
    );
  }
}
