class CollectionInfo {
  final String name;
  final int count;

  CollectionInfo({required this.name, required this.count});

  factory CollectionInfo.fromJson(Map<String, dynamic> json) {
    return CollectionInfo(
      name: json['name'] as String? ?? '',
      count: json['count'] as int? ?? 0,
    );
  }
}

class SourceChunk {
  final String chunkId;
  final String text;
  final double distance;

  SourceChunk({
    required this.chunkId,
    required this.text,
    required this.distance,
  });

  factory SourceChunk.fromJson(Map<String, dynamic> json) {
    return SourceChunk(
      chunkId: json['chunk_id'] as String? ?? '',
      text: json['text'] as String? ?? '',
      distance: (json['distance'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class QueryResponse {
  final String answer;
  final String collectionName;
  final String question;
  final List<SourceChunk> sources;
  final int chunksUsed;

  QueryResponse({
    required this.answer,
    required this.collectionName,
    required this.question,
    required this.sources,
    required this.chunksUsed,
  });

  factory QueryResponse.fromJson(Map<String, dynamic> json) {
    var rawSources = json['sources'] as List<dynamic>? ?? [];
    List<SourceChunk> parsedSources =
        rawSources.map((s) => SourceChunk.fromJson(s as Map<String, dynamic>)).toList();

    return QueryResponse(
      answer: json['answer'] as String? ?? '',
      collectionName: json['collection_name'] as String? ?? '',
      question: json['question'] as String? ?? '',
      sources: parsedSources,
      chunksUsed: json['chunks_used'] as int? ?? 0,
    );
  }
}

class UploadResponse {
  final String status;
  final String collectionName;
  final String filename;
  final int chunksStored;
  final int chunkSize;
  final int chunkOverlap;

  UploadResponse({
    required this.status,
    required this.collectionName,
    required this.filename,
    required this.chunksStored,
    required this.chunkSize,
    required this.chunkOverlap,
  });

  factory UploadResponse.fromJson(Map<String, dynamic> json) {
    return UploadResponse(
      status: json['status'] as String? ?? 'ok',
      collectionName: json['collection_name'] as String? ?? '',
      filename: json['filename'] as String? ?? '',
      chunksStored: json['chunks_stored'] as int? ?? 0,
      chunkSize: json['chunk_size'] as int? ?? 0,
      chunkOverlap: json['chunk_overlap'] as int? ?? 0,
    );
  }
}

class ChatMessage {
  final String id;
  final String sender; // 'user' or 'ai'
  final String text;
  final DateTime timestamp;
  final List<SourceChunk>? sources;
  final bool isLoading;

  ChatMessage({
    required this.id,
    required this.sender,
    required this.text,
    required this.timestamp,
    this.sources,
    this.isLoading = false,
  });
}
