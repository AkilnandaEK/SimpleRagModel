import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/benchmark_models.dart';

void main() {
  group('ArchitectureBenchmarkResult.fromJson', () {
    test('parses a representative backend payload', () {
      final json = {
        'architecture': 'agent',
        'success_rate': 40.0,
        'successful_count': 4,
        'total_count': 10,
        'p50_latency_ms': 17.71,
        'p99_latency_ms': 47.56,
        'avg_input_tokens': 121.6,
        'avg_output_tokens': 121.6,
        'avg_total_tokens': 243.2,
        'total_tokens': 2432,
        'total_cost_usd': 0.000657,
        'avg_cost_per_run': 0.000066,
        'cost_per_success': 0.000164,
      };

      final result = ArchitectureBenchmarkResult.fromJson(json);

      expect(result.architecture, 'agent');
      expect(result.successRate, 40.0);
      expect(result.successfulCount, 4);
      expect(result.totalCount, 10);
      expect(result.p50LatencyMs, 17.71);
      expect(result.p99LatencyMs, 47.56);
      expect(result.avgInputTokens, 121.6);
      expect(result.avgOutputTokens, 121.6);
      expect(result.avgTotalTokens, 243.2);
      expect(result.totalTokens, 2432);
      expect(result.totalCostUsd, 0.000657);
      expect(result.avgCostPerRun, closeTo(0.000066, 1e-7));
      expect(result.costPerSuccess, closeTo(0.000164, 1e-7));
    });

    test('defaults optional fields to 0 when omitted', () {
      final json = {
        'architecture': 'workflow',
        'success_rate': 10.0,
        'successful_count': 1,
        'total_count': 10,
        'p50_latency_ms': 5.0,
        'p99_latency_ms': 50.0,
        'avg_input_tokens': 50.0,
        'avg_output_tokens': 50.0,
        'avg_total_tokens': 100.0,
        'total_tokens': 1000,
        'total_cost_usd': 0.0001,
        'avg_cost_per_run': 0.00001,
        'cost_per_success': 0.0001,
      };

      final result = ArchitectureBenchmarkResult.fromJson(json);
      expect(result.architecture, 'workflow');
      expect(result.successRate, 10.0);
    });
  });

  group('ScenarioResult.fromJson', () {
    test('parses an agent-correct scenario', () {
      final json = {
        'id': 'easy:01',
        'level': 'easy',
        'is_negative_case': false,
        'question': 'What is the API key?',
        'agent_correct': true,
        'agent_match_type': 'Context Only',
        'workflow_correct': false,
        'workflow_match_type': '',
      };

      final scenario = ScenarioResult.fromJson(json);

      expect(scenario.id, 'easy:01');
      expect(scenario.level, 'easy');
      expect(scenario.isNegativeCase, false);
      expect(scenario.question, 'What is the API key?');
      expect(scenario.agentCorrect, true);
      expect(scenario.agentMatchType, 'Context Only');
      expect(scenario.workflowCorrect, false);
      expect(scenario.workflowMatchType, '');
    });

    test('parses a negative-case scenario', () {
      final json = {
        'id': 'easy:06',
        'level': 'easy',
        'is_negative_case': true,
        'question': 'List all users',
        'agent_correct': true,
        'agent_match_type': 'Exact Match',
        'workflow_correct': true,
        'workflow_match_type': 'Exact Match',
      };

      final scenario = ScenarioResult.fromJson(json);
      expect(scenario.isNegativeCase, true);
      expect(scenario.agentCorrect, true);
      expect(scenario.workflowCorrect, true);
    });
  });

  group('BenchmarkResult.fromJson', () {
    test('parses full response with both architectures', () {
      final json = {
        'scenario_ids': ['easy:01', 'easy:04'],
        'agent': {
          'architecture': 'agent',
          'success_rate': 40.0,
          'successful_count': 4,
          'total_count': 10,
          'p50_latency_ms': 17.71,
          'p99_latency_ms': 47.56,
          'avg_input_tokens': 121.6,
          'avg_output_tokens': 121.6,
          'avg_total_tokens': 243.2,
          'total_tokens': 2432,
          'total_cost_usd': 0.000657,
          'avg_cost_per_run': 0.000066,
          'cost_per_success': 0.000164,
        },
        'workflow': {
          'architecture': 'workflow',
          'success_rate': 50.0,
          'successful_count': 5,
          'total_count': 10,
          'p50_latency_ms': 3.2,
          'p99_latency_ms': 11.5,
          'avg_input_tokens': 100.0,
          'avg_output_tokens': 100.0,
          'avg_total_tokens': 200.0,
          'total_tokens': 2000,
          'total_cost_usd': 0.0003,
          'avg_cost_per_run': 0.00003,
          'cost_per_success': 0.00006,
        },
        'scenario_results': [
          {
            'id': 'easy:01',
            'level': 'easy',
            'is_negative_case': false,
            'question': 'How to authenticate?',
            'agent_correct': false,
            'agent_match_type': '',
            'workflow_correct': true,
            'workflow_match_type': 'Exact Match',
          },
        ],
      };

      final result = BenchmarkResult.fromJson(json);

      expect(result.scenarioIds, ['easy:01', 'easy:04']);
      expect(result.agent.successRate, 40.0);
      expect(result.workflow.successRate, 50.0);
      expect(result.scenarioResults.length, 1);
      expect(result.scenarioResults.first.id, 'easy:01');
    });

    test('winnerLabel is Workflow when success rate is higher', () {
      final result = BenchmarkResult(
        scenarioIds: ['easy:01'],
        agent: const ArchitectureBenchmarkResult(
          architecture: 'agent',
          successRate: 40.0,
          successfulCount: 4,
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
        workflow: const ArchitectureBenchmarkResult(
          architecture: 'workflow',
          successRate: 50.0,
          successfulCount: 5,
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

      expect(result.winnerLabel, 'Workflow');
      expect(result.winnerSuccessRate, 50.0);
      expect(result.agentPassCount, 0);
      expect(result.workflowPassCount, 0);
      expect(result.scenarioCount, 1); // Falls back to scenarioIds.length
    });

    test('winnerLabel is Draw when success rates match', () {
      final result = BenchmarkResult(
        scenarioIds: [],
        agent: const ArchitectureBenchmarkResult(
          architecture: 'agent',
          successRate: 50.0,
          successfulCount: 5,
          totalCount: 10,
          p50LatencyMs: 10.0,
          p99LatencyMs: 40.0,
          avgInputTokens: 100.0,
          avgOutputTokens: 100.0,
          avgTotalTokens: 200.0,
          totalTokens: 2000,
          totalCostUsd: 0.0005,
          avgCostPerRun: 0.00005,
          costPerSuccess: 0.0001,
        ),
        workflow: const ArchitectureBenchmarkResult(
          architecture: 'workflow',
          successRate: 50.0,
          successfulCount: 5,
          totalCount: 10,
          p50LatencyMs: 3.0,
          p99LatencyMs: 12.0,
          avgInputTokens: 80.0,
          avgOutputTokens: 80.0,
          avgTotalTokens: 160.0,
          totalTokens: 1600,
          totalCostUsd: 0.0003,
          avgCostPerRun: 0.00003,
          costPerSuccess: 0.00006,
        ),
        scenarioResults: const [],
      );

      expect(result.winnerLabel, 'Draw');
      expect(result.winnerSuccessRate, 50.0);
    });

    test('winnerLabel is Agent when agent success rate is higher', () {
      final result = BenchmarkResult(
        scenarioIds: [],
        agent: const ArchitectureBenchmarkResult(
          architecture: 'agent',
          successRate: 70.0,
          successfulCount: 7,
          totalCount: 10,
          p50LatencyMs: 12.0,
          p99LatencyMs: 35.0,
          avgInputTokens: 110.0,
          avgOutputTokens: 110.0,
          avgTotalTokens: 220.0,
          totalTokens: 2200,
          totalCostUsd: 0.0006,
          avgCostPerRun: 0.00006,
          costPerSuccess: 0.000086,
        ),
        workflow: const ArchitectureBenchmarkResult(
          architecture: 'workflow',
          successRate: 30.0,
          successfulCount: 3,
          totalCount: 10,
          p50LatencyMs: 4.0,
          p99LatencyMs: 15.0,
          avgInputTokens: 90.0,
          avgOutputTokens: 90.0,
          avgTotalTokens: 180.0,
          totalTokens: 1800,
          totalCostUsd: 0.00025,
          avgCostPerRun: 0.000025,
          costPerSuccess: 0.000083,
        ),
        scenarioResults: const [],
      );

      expect(result.winnerLabel, 'Agent');
      expect(result.winnerSuccessRate, 70.0);
    });

    test('insightLines are generated, not hardcoded', () {
      final result = BenchmarkResult(
        scenarioIds: [],
        agent: const ArchitectureBenchmarkResult(
          architecture: 'agent',
          successRate: 40.0,
          successfulCount: 4,
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
        workflow: const ArchitectureBenchmarkResult(
          architecture: 'workflow',
          successRate: 50.0,
          successfulCount: 5,
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

      expect(result.insightLines, isNotEmpty);
      // First line is always the winner statement.
      expect(result.insightLines.first, contains('Workflow'));
      // Last line is always the scope caveat.
      expect(result.insightLines.last, contains('not a general claim'));
      // Insight mentions a concrete efficiency fact.
      expect(
        result.insightLines.any((l) => l.contains('tokens') || l.contains('cost')),
        isTrue,
      );
    });
  });
}
