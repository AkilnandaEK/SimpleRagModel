import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../models/benchmark_models.dart';
import '../models/rag_models.dart';
import '../models/trajectory_models.dart';
import '../models/week10_race_models.dart';

class ApiService {
  static String get baseUrl {
    if (kIsWeb) {
      final Uri currentUri = Uri.base;
      if (currentUri.port == 8000) {
        return '${currentUri.scheme}://${currentUri.host}:${currentUri.port}';
      }
    }
    return 'http://127.0.0.1:8000';
  }

  /// Check server health
  static Future<bool> checkHealth() async {
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/'))
          .timeout(const Duration(seconds: 4));
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// GET /collections
  static Future<List<CollectionInfo>> fetchCollections() async {
    final response = await http.get(Uri.parse('$baseUrl/collections'));
    if (response.statusCode == 200) {
      final List<dynamic> data = jsonDecode(response.body);
      return data
          .map((item) => CollectionInfo.fromJson(item as Map<String, dynamic>))
          .toList();
    } else {
      throw Exception('Failed to fetch collections: ${response.statusCode}');
    }
  }

  /// POST /upload
  static Future<UploadResponse> uploadPdf({
    required List<int> bytes,
    required String filename,
    String collectionName = '',
    String sdkVersion = 'v3',
    String pageType = 'reference',
    int chunkSize = 0,
    int chunkOverlap = 0,
  }) async {
    final uri = Uri.parse('$baseUrl/upload');
    final request = http.MultipartRequest('POST', uri);

    request.files.add(
      http.MultipartFile.fromBytes('file', bytes, filename: filename),
    );

    if (collectionName.isNotEmpty) {
      request.fields['collection_name'] = collectionName;
    }
    request.fields['sdk_version'] = sdkVersion;
    request.fields['page_type'] = pageType;

    if (chunkSize > 0) {
      request.fields['chunk_size'] = chunkSize.toString();
    }
    if (chunkOverlap > 0) {
      request.fields['chunk_overlap'] = chunkOverlap.toString();
    }

    final streamedResponse = await request.send();
    final response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode == 200) {
      final Map<String, dynamic> data = jsonDecode(response.body);
      return UploadResponse.fromJson(data);
    } else {
      final errorData = jsonDecode(response.body);
      final detail = errorData['detail'] ?? 'Upload failed';
      throw Exception(detail);
    }
  }

  /// POST /query
  static Future<QueryResponse> askQuestion({
    required String question,
    required String collectionName,
    int topK = 0,
    String? sdkVersion,
    bool debug = true,
  }) async {
    final bodyMap = <String, dynamic>{
      'question': question,
      'collection_name': collectionName,
      'top_k': topK,
      'debug': debug,
    };
    if (sdkVersion != null && sdkVersion.isNotEmpty) {
      bodyMap['sdk_version'] = sdkVersion;
    }

    final response = await http.post(
      Uri.parse('$baseUrl/query'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(bodyMap),
    );

    if (response.statusCode == 200) {
      final Map<String, dynamic> data = jsonDecode(response.body);
      return QueryResponse.fromJson(data);
    } else {
      final errorData = jsonDecode(response.body);
      final detail = errorData['detail'] ?? 'Query failed';
      throw Exception(detail);
    }
  }

  /// GET /eval/mrr
  ///
  /// Scores the golden set with MRR@k. [split] restricts to 'dev' or 'test';
  /// null scores everything and still returns the per-split breakdown.
  static Future<MrrReport> fetchMrrReport({
    String? collectionName,
    int topK = 0,
    String? split,
  }) async {
    final params = <String, String>{};
    if (collectionName != null && collectionName.isNotEmpty) {
      params['collection_name'] = collectionName;
    }
    if (topK > 0) params['top_k'] = topK.toString();
    if (split != null && split.isNotEmpty) params['split'] = split;

    final uri = Uri.parse(
      '$baseUrl/eval/mrr',
    ).replace(queryParameters: params.isEmpty ? null : params);

    final response = await http.get(uri);

    if (response.statusCode == 200) {
      return MrrReport.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }

    String detail = 'MRR evaluation failed (${response.statusCode})';
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map && decoded['detail'] != null) {
        detail = decoded['detail'].toString();
      }
    } catch (_) {
      // Non-JSON error body — keep the status-code message.
    }
    throw Exception(detail);
  }

  /// POST /api/benchmark/run
  ///
  /// Runs the standardised Agent vs Workflow benchmark through the existing
  /// backend runner. The benchmark can take a while, so no artificial timeout
  /// is applied — the request stays open until the backend returns.
  ///
  /// [scenarioIds] is optional; when omitted the backend runs its default
  /// 10-scenario set.
  static Future<BenchmarkResult> runBenchmark({
    List<String>? scenarioIds,
  }) async {
    final bodyMap = <String, dynamic>{};
    if (scenarioIds != null && scenarioIds.isNotEmpty) {
      bodyMap['scenario_ids'] = scenarioIds;
    }

    final response = await http.post(
      Uri.parse('$baseUrl/api/benchmark/run'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(bodyMap),
    );

    if (response.statusCode == 200) {
      return BenchmarkResult.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }

    String detail = 'Benchmark failed (${response.statusCode})';
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map && decoded['detail'] != null) {
        detail = decoded['detail'].toString();
      }
    } catch (_) {
      // Non-JSON error body — keep the status-code message.
    }
    throw Exception(detail);
  }

  /// POST /api/benchmark/week10/race
  ///
  /// Runs the Week 10 "Single Agent vs Multi-Agent Squad" race and returns the
  /// live `RaceResult.to_dict()` payload.
  ///
  /// This is the execution path for the Week 10 benchmark button. It is
  /// deliberately a different endpoint from [runBenchmark] (`/api/benchmark/run`),
  /// which belongs to the separate Agent-vs-Workflow experiment and is left
  /// untouched.
  ///
  /// The race is expensive — it warms up the embedding model and Chroma, then
  /// runs every case through both arms (the Single Agent arm makes real LLM
  /// calls). No timeout is applied so the request stays open until the backend
  /// finishes, exactly like [runBenchmark].
  ///
  /// [caseIds] is optional; when omitted the backend runs the sanctioned Week 10
  /// 10-case set.
  static Future<Week10RaceResult> runWeek10Race({List<String>? caseIds}) async {
    final bodyMap = <String, dynamic>{};
    if (caseIds != null && caseIds.isNotEmpty) {
      bodyMap['case_ids'] = caseIds;
    }

    final response = await http.post(
      Uri.parse('$baseUrl/api/benchmark/week10/race'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(bodyMap),
    );

    if (response.statusCode == 200) {
      return Week10RaceResult.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }

    String detail = 'Week 10 race failed (${response.statusCode})';
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map && decoded['detail'] != null) {
        detail = decoded['detail'].toString();
      }
    } catch (_) {
      // Non-JSON error body — keep the status-code message.
    }
    throw Exception(detail);
  }

  ///
  /// Runs the Week 8 trajectory evaluation suite. This executes every query
  /// twice (baseline + mitigated) plus the injection suite, so it is slow —
  /// several minutes against a live provider. No client timeout is applied;
  /// the request stays open until the backend returns.
  static Future<TrajectoryReport> runTrajectoryEval({
    String? mode,
    String? provider,
    String? model,
    bool includeInjection = true,
  }) async {
    final bodyMap = <String, dynamic>{'include_injection': includeInjection};
    if (mode != null && mode.isNotEmpty) bodyMap['mode'] = mode;
    if (provider != null && provider.isNotEmpty) bodyMap['provider'] = provider;
    if (model != null && model.isNotEmpty) bodyMap['model'] = model;

    final response = await http.post(
      Uri.parse('$baseUrl/api/trajectory/run'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(bodyMap),
    );

    if (response.statusCode == 200) {
      return TrajectoryReport.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>,
      );
    }

    String detail = 'Trajectory eval failed (${response.statusCode})';
    try {
      final decoded = jsonDecode(response.body);
      if (decoded is Map && decoded['detail'] != null) {
        detail = decoded['detail'].toString();
      }
    } catch (_) {
      // Non-JSON error body — keep the status-code message.
    }
    throw Exception(detail);
  }

  /// DELETE /collections/{name}
  static Future<bool> deleteCollection(String collectionName) async {
    final encodedName = Uri.encodeComponent(collectionName);
    final response = await http.delete(
      Uri.parse('$baseUrl/collections/$encodedName'),
    );
    return response.statusCode == 200;
  }
}
