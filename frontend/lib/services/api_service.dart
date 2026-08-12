import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../models/rag_models.dart';

class ApiService {
  static String get baseUrl {
    if (kIsWeb) {
      // In web, if hosted on the same origin (FastAPI), use relative or current origin.
      // For local flutter dev server, default to http://127.0.0.1:8000
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
      final response = await http.get(Uri.parse('$baseUrl/')).timeout(
            const Duration(seconds: 4),
          );
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
    int chunkSize = 0,
    int chunkOverlap = 0,
  }) async {
    final uri = Uri.parse('$baseUrl/upload');
    final request = http.MultipartRequest('POST', uri);

    request.files.add(
      http.MultipartFile.fromBytes(
        'file',
        bytes,
        filename: filename,
      ),
    );

    if (collectionName.isNotEmpty) {
      request.fields['collection_name'] = collectionName;
    }
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
  }) async {
    final response = await http.post(
      Uri.parse('$baseUrl/query'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'question': question,
        'collection_name': collectionName,
        'top_k': topK,
      }),
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

  /// DELETE /collections/{name}
  static Future<bool> deleteCollection(String collectionName) async {
    final encodedName = Uri.encodeComponent(collectionName);
    final response = await http.delete(
      Uri.parse('$baseUrl/collections/$encodedName'),
    );
    return response.statusCode == 200;
  }
}
