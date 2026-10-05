import 'dart:async';
import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'models/benchmark_models.dart';
import 'models/rag_models.dart';
import 'models/trajectory_models.dart';
import 'models/week10_race_models.dart';
import 'services/api_service.dart';
import 'widgets/benchmark_view.dart';
import 'widgets/chat_view.dart';
import 'widgets/sidebar.dart';
import 'widgets/trajectory_view.dart';
import 'widgets/week10_race_view.dart';

/// The workspace's top-level tabs. Chat is the product; Evals is the lab that
/// measures it.
enum WorkspaceTab { chat, evals }

void main() {
  runApp(const RagApp());
}

class RagApp extends StatelessWidget {
  const RagApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'RAG Intelligence Hub & Evaluation Lab',
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
  bool _debugMode = true; // Evaluation & debug mode enabled by default
  final Map<String, List<ChatMessage>> _chatHistory = {};
  BenchmarkResult? _benchmarkResult;

  /// Last live Week 10 race result, so reopening the dialog can show it.
  Week10RaceResult? _week10Result;

  /// True while the Week 10 race dialog is open and executing.
  bool _isWeek10Running = false;
  bool _isBackendConnected = false;
  Timer? _healthTimer;
  WorkspaceTab _tab = WorkspaceTab.chat;

  /// Kept at this level so switching tabs does not discard a completed run —
  /// the trajectory suite takes minutes and must survive navigation.
  TrajectoryReport? _trajectoryReport;

  @override
  void initState() {
    super.initState();
    _checkHealthAndLoad();
    _healthTimer = Timer.periodic(
      const Duration(seconds: 10),
      (_) => _checkHealth(),
    );
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

  void _openBenchmarkDialog() {
    showBenchmarkDialog(
      context,
      previousResult: _benchmarkResult,
      onResult: (result) => setState(() => _benchmarkResult = result),
    );
  }

  /// Opens the live Week 10 Single Agent vs Multi-Agent Squad benchmark.
  ///
  /// The dialog owns the run lifecycle (initial / loading / success / error) and
  /// calls `POST /api/benchmark/week10/race`. This callback only tracks whether
  /// a race is in flight so the sidebar action can be disabled meanwhile.
  void _openWeek10Results() {
    setState(() => _isWeek10Running = true);
    showWeek10RaceDialog(
      context,
      previousResult: _week10Result,
      onResult: (result) => setState(() => _week10Result = result),
    ).whenComplete(() {
      if (mounted) setState(() => _isWeek10Running = false);
    });
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
        debug: _debugMode,
      );

      final aiMsg = ChatMessage(
        id: DateTime.now().millisecondsSinceEpoch.toString(),
        sender: 'ai',
        text: response.answer,
        timestamp: DateTime.now(),
        sources: response.sources,
        evaluation: response.evaluation,
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
            onOpenBenchmark: _openBenchmarkDialog,
            onOpenWeek10Results: _openWeek10Results,
            isWeek10Running: _isWeek10Running,
            activeTab: _tab,
            onSelectTab: (tab) => setState(() => _tab = tab),
          ),
          Expanded(
            // IndexedStack, not a switch: the Evals tab holds an in-progress or
            // completed multi-minute run, and rebuilding it on every tab change
            // would throw that away.
            child: IndexedStack(
              index: _tab.index,
              children: [
                ChatView(
                  selectedCollection: _selectedCollection,
                  debugMode: _debugMode,
                  onDebugModeChanged: (val) {
                    setState(() => _debugMode = val);
                  },
                  messages: activeMessages,
                  onSendQuestion: _onSendQuestion,
                ),
                TrajectoryView(
                  previousReport: _trajectoryReport,
                  onReport: (report) =>
                      setState(() => _trajectoryReport = report),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
