import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/benchmark_models.dart';
import 'package:frontend/widgets/benchmark_view.dart';

BenchmarkResult _makeResult({
  double agentRate = 40.0,
  double workflowRate = 50.0,
}) =>
    BenchmarkResult(
      scenarioIds: const ['easy:01', 'easy:04'],
      agent: ArchitectureBenchmarkResult(
        architecture: 'agent',
        successRate: agentRate,
        successfulCount: agentRate == 40 ? 4 : 7,
        totalCount: 10,
        p50LatencyMs: 17.71,
        p99LatencyMs: 47.56,
        avgInputTokens: 121.6,
        avgOutputTokens: 121.6,
        avgTotalTokens: 243.2,
        totalTokens: 2432,
        totalCostUsd: 0.000657,
        avgCostPerRun: 0.000066,
        costPerSuccess: 0.000164,
      ),
      workflow: ArchitectureBenchmarkResult(
        architecture: 'workflow',
        successRate: workflowRate,
        successfulCount: workflowRate == 50 ? 5 : 7,
        totalCount: 10,
        p50LatencyMs: 3.2,
        p99LatencyMs: 11.5,
        avgInputTokens: 100.0,
        avgOutputTokens: 100.0,
        avgTotalTokens: 200.0,
        totalTokens: 2000,
        totalCostUsd: 0.0003,
        avgCostPerRun: 0.00003,
        costPerSuccess: 0.00006,
      ),
      scenarioResults: const [],
    );

Widget _wrap(Widget child) => MaterialApp(
      home: Scaffold(
        backgroundColor: const Color(0xFF0B0F19),
        body: Center(child: child),
      ),
    );

void main() {
  group('BenchmarkView', () {
    testWidgets('shows empty hint when no previousResult and status is initial',
        (tester) async {
      await tester.pumpWidget(_wrap(const BenchmarkView()));
      await tester.pumpAndSettle();

      expect(find.text('No benchmark run yet'), findsOneWidget);
      expect(
        find.text('Run Agent vs Workflow Benchmark'),
        findsOneWidget,
      );
    });

    testWidgets('shows previousResult on initial state', (tester) async {
      final result = _makeResult();
      await tester.pumpWidget(
        _wrap(BenchmarkView(previousResult: result)),
      );
      await tester.pumpAndSettle();

      // Winner card should be visible.
      expect(find.text('OVERALL WINNER'), findsOneWidget);
      expect(find.text('Workflow'), findsWidgets);
      // Primary Run button still visible for a new run.
      expect(
        find.text('Run Agent vs Workflow Benchmark'),
        findsOneWidget,
      );
    });

    testWidgets('clicking Run with runOverride shows loading then success',
        (tester) async {
      final completer = Completer<BenchmarkResult>();
      final result = _makeResult();

      await tester.pumpWidget(_wrap(BenchmarkView(
        runOverride: () => completer.future,
      )));
      await tester.pumpAndSettle();

      // Tap Run.
      await tester.tap(find.text('Run Agent vs Workflow Benchmark'));
      await tester.pump();
      await tester.pump();

      // Should be in loading state.
      expect(
        find.text('Running Agent vs Workflow benchmark...'),
        findsOneWidget,
      );
      expect(find.byType(CircularProgressIndicator), findsWidgets);

      // Complete the future.
      completer.complete(result);
      await tester.pumpAndSettle();

      // Should now show success state.
      expect(find.text('OVERALL WINNER'), findsOneWidget);
      expect(find.text('Workflow'), findsWidgets);
    });

    testWidgets('shows error state when runOverride throws', (tester) async {
      await tester.pumpWidget(_wrap(BenchmarkView(
        runOverride: () => Future.error(Exception('Connection refused')),
      )));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Run Agent vs Workflow Benchmark'));
      await tester.pump();
      await tester.pump();
      await tester.pumpAndSettle();

      expect(find.text('Benchmark failed'), findsOneWidget);
      expect(find.textContaining('Connection refused'), findsOneWidget);
      expect(find.text('Retry Benchmark'), findsOneWidget);
    });

    testWidgets('Retry re-runs and recovers on success', (tester) async {
      int callCount = 0;
      final completer = Completer<BenchmarkResult>();

      await tester.pumpWidget(_wrap(BenchmarkView(
        runOverride: () {
          callCount++;
          if (callCount == 1) {
            return Future.error(Exception('Temporary failure'));
          }
          return completer.future;
        },
      )));
      await tester.pumpAndSettle();

      // First run — should error.
      await tester.tap(find.text('Run Agent vs Workflow Benchmark'));
      await tester.pump();
      await tester.pump();
      await tester.pumpAndSettle();
      expect(find.text('Benchmark failed'), findsOneWidget);

      // Retry — should succeed.
      await tester.tap(find.text('Retry Benchmark'));
      await tester.pump();
      await tester.pump();
      completer.complete(_makeResult());
      await tester.pumpAndSettle();

      expect(find.text('OVERALL WINNER'), findsOneWidget);
      expect(find.text('Workflow'), findsOneWidget);
    });

    testWidgets('onResult callback fires when run succeeds', (tester) async {
      BenchmarkResult? reported;
      final result = _makeResult();

      await tester.pumpWidget(_wrap(BenchmarkView(
        onResult: (r) => reported = r,
        runOverride: () => Future.value(result),
      )));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Run Agent vs Workflow Benchmark'));
      await tester.pumpAndSettle();

      expect(reported, isNotNull);
      expect(reported!.winnerLabel, 'Workflow');
    });

    testWidgets('button shows loading text while running', (tester) async {
      final completer = Completer<BenchmarkResult>();

      await tester.pumpWidget(_wrap(BenchmarkView(
        runOverride: () => completer.future,
      )));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Run Agent vs Workflow Benchmark'));
      await tester.pump();
      await tester.pump();

      // The run override is still pending — button text should be the
      // loading text, not the run text.
      expect(
        find.textContaining('Running Agent vs Workflow benchmark'),
        findsOneWidget,
      );

      completer.complete(_makeResult());
      await tester.pumpAndSettle();
    });

    testWidgets('close button dismisses the dialog', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: ElevatedButton(
                onPressed: () => showDialog(
                  context: context,
                  builder: (_) => const BenchmarkView(),
                ),
                child: const Text('Open'),
              ),
            ),
          ),
        ),
      ));
      await tester.pumpAndSettle();

      // Open the dialog.
      await tester.tap(find.text('Open'));
      await tester.pumpAndSettle();
      expect(find.text('No benchmark run yet'), findsOneWidget);

      // Close via button.
      await tester.tap(find.text('Close'));
      await tester.pumpAndSettle();
      expect(find.text('No benchmark run yet'), findsNothing);
    });
  });
}
