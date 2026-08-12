import 'dart:async';
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'models/rag_models.dart';
import 'services/api_service.dart';
import 'widgets/chat_view.dart';
import 'widgets/sidebar.dart';

void main() {
  runApp(const RagApp());
}

class RagApp extends StatelessWidget {
  const RagApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'RAG Intelligence Hub',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0B0F19),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF6366F1),
          secondary: Color(0xFF8B5CF6),
          surface: Color(0xFF1E293B),
        ),
        textTheme: GoogleFonts.interTextTheme(ThemeData.dark().textTheme),
        useMaterial3: true,
      ),
      home: const MainWorkspace(),
    );
  }
}

class MainWorkspace extends StatefulWidget {
  const MainWorkspace({super.key});

  @override
  State<MainWorkspace> createState() => _MainWorkspaceState();
}

class _MainWorkspaceState extends State<MainWorkspace> {
  List<CollectionInfo> _collections = [];
  String? _selectedCollection;
  final Map<String, List<ChatMessage>> _chatHistory = {};
  bool _isBackendConnected = false;
  Timer? _healthTimer;

  @override
  void initState() {
    super.initState();
    _checkHealthAndLoad();
    // Poll backend health every 10 seconds
    _healthTimer = Timer.periodic(const Duration(seconds: 10), (_) => _checkHealth());
  }

  @override
  void dispose() {
    _healthTimer?.cancel();
    super.dispose();
  }

  Future<void> _checkHealth() async {
    final ok = await ApiService.checkHealth();
    if (mounted) {
      setState(() => _isBackendConnected = ok);
    }
  }

  Future<void> _checkHealthAndLoad() async {
    final ok = await ApiService.checkHealth();
    if (mounted) {
      setState(() => _isBackendConnected = ok);
    }
    if (ok) {
      await _refreshCollections();
    }
  }

  Future<void> _refreshCollections() async {
    try {
      final cols = await ApiService.fetchCollections();
      if (mounted) {
        setState(() {
          _collections = cols;
          if (_selectedCollection != null &&
              !cols.any((c) => c.name == _selectedCollection)) {
            _selectedCollection = cols.isNotEmpty ? cols.first.name : null;
          } else if (_selectedCollection == null && cols.isNotEmpty) {
            _selectedCollection = cols.first.name;
          }
        });
      }
    } catch (_) {
      // Handled silently
    }
  }

  Future<void> _onSendQuestion(String question) async {
    if (_selectedCollection == null) return;
    final currentCollection = _selectedCollection!;

    final userMsg = ChatMessage(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      sender: 'user',
      text: question,
      timestamp: DateTime.now(),
    );

    final loadingMsg = ChatMessage(
      id: '${DateTime.now().millisecondsSinceEpoch}_loading',
      sender: 'ai',
      text: '',
      timestamp: DateTime.now(),
      isLoading: true,
    );

    setState(() {
      _chatHistory.putIfAbsent(currentCollection, () => []);
      _chatHistory[currentCollection]!.add(userMsg);
      _chatHistory[currentCollection]!.add(loadingMsg);
    });

    try {
      final response = await ApiService.askQuestion(
        question: question,
        collectionName: currentCollection,
      );

      final aiMsg = ChatMessage(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        sender: 'ai',
        text: response.answer,
        timestamp: DateTime.now(),
        sources: response.sources,
      );

      setState(() {
        final list = _chatHistory[currentCollection]!;
        list.removeWhere((m) => m.id == loadingMsg.id);
        list.add(aiMsg);
      });
    } catch (e) {
      final errorMsg = ChatMessage(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        sender: 'ai',
        text: 'Error: ${e.toString().replaceAll("Exception: ", "")}',
        timestamp: DateTime.now(),
      );

      setState(() {
        final list = _chatHistory[currentCollection]!;
        list.removeWhere((m) => m.id == loadingMsg.id);
        list.add(errorMsg);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final activeMessages = _selectedCollection != null
        ? (_chatHistory[_selectedCollection!] ?? [])
        : <ChatMessage>[];

    return Scaffold(
      body: Row(
        children: [
          Sidebar(
            collections: _collections,
            selectedCollection: _selectedCollection,
            onSelectCollection: (colName) {
              setState(() => _selectedCollection = colName);
            },
            onRefresh: _refreshCollections,
            isBackendConnected: _isBackendConnected,
          ),
          Expanded(
            child: ChatView(
              selectedCollection: _selectedCollection,
              messages: activeMessages,
              onSendQuestion: _onSendQuestion,
            ),
          ),
        ],
      ),
    );
  }
}
