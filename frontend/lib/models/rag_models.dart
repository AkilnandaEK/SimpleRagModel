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
  final String? sourceFile;
  final String? pageId;
  final String? anchor;
  final String? citation;
  final Map<String, dynamic>? metadata;

  SourceChunk({
    required this.chunkId,
    required this.text,
    required this.distance,
    this.sourceFile,
    this.pageId,
    this.anchor,
    this.citation,
    this.metadata,
  });

  factory SourceChunk.fromJson(Map<String, dynamic> json) {
    return SourceChunk(
      chunkId: json['chunk_id'] as String? ?? '',
      text: json['text'] as String? ?? '',
      distance: (json['distance'] as num?)?.toDouble() ?? 0.0,
      sourceFile: json['source_file'] as String?,
      pageId: json['page_id'] as String?,
      anchor: json['anchor'] as String?,
      citation: json['citation'] as String?,
      metadata: json['metadata'] as Map<String, dynamic>?,
    );
  }
}

class CitationDetail {
  final String chunkId;
  final String? sourceFile;
  final String? pageId;
  final String? anchor;
  final String? section;

  CitationDetail({
    required this.chunkId,
    this.sourceFile,
    this.pageId,
    this.anchor,
    this.section,
  });

  factory CitationDetail.fromJson(Map<String, dynamic> json) {
    return CitationDetail(
      chunkId: json['chunk_id'] as String? ?? '',
      sourceFile: json['source_file'] as String?,
      pageId: json['page_id'] as String?,
      anchor: json['anchor'] as String?,
      section: json['section'] as String?,
    );
  }
}

class EvaluationChunk {
  final int rank;
  final String chunkId;
  final String text;
  final double distance;
  final double? similarityScore;
  final String? sourceFile;
  final String? pageId;
  final String? page;
  final String? sdkVersion;
  final String? pageType;
  final String? section;
  final String? parentSection;
  final String? anchor;
  final int? chunkIndex;
  final Map<String, dynamic> metadata;

  EvaluationChunk({
    required this.rank,
    required this.chunkId,
    required this.text,
    required this.distance,
    this.similarityScore,
    this.sourceFile,
    this.pageId,
    this.page,
    this.sdkVersion,
    this.pageType,
    this.section,
    this.parentSection,
    this.anchor,
    this.chunkIndex,
    required this.metadata,
  });

  factory EvaluationChunk.fromJson(Map<String, dynamic> json) {
    return EvaluationChunk(
      rank: json['rank'] as int? ?? 1,
      chunkId: json['chunk_id'] as String? ?? '',
      text: json['text'] as String? ?? '',
      distance: (json['distance'] as num?)?.toDouble() ?? 0.0,
      similarityScore: (json['similarity_score'] as num?)?.toDouble(),
      sourceFile: json['source_file'] as String?,
      pageId: json['page_id'] as String?,
      page: json['page'] as String?,
      sdkVersion: json['sdk_version'] as String?,
      pageType: json['page_type'] as String?,
      section: json['section'] as String?,
      parentSection: json['parent_section'] as String?,
      anchor: json['anchor'] as String?,
      chunkIndex: json['chunk_index'] as int?,
      metadata: json['metadata'] as Map<String, dynamic>? ?? {},
    );
  }
}

class EvaluationDetails {
  final bool enabled;
  final String query;
  final String collectionName;
  final String chunkingStrategy;
  final String? sdkVersion;
  final int topK;
  final Map<String, dynamic>? metadataFilter;
  final List<EvaluationChunk> retrievedChunks;
  final String context;
  final String llmPrompt;
  final String llmResponse;
  final String answer;
  final String responseStatus;
  final List<CitationDetail> citations;

  EvaluationDetails({
    required this.enabled,
    required this.query,
    required this.collectionName,
    required this.chunkingStrategy,
    this.sdkVersion,
    required this.topK,
    this.metadataFilter,
    required this.retrievedChunks,
    required this.context,
    required this.llmPrompt,
    required this.llmResponse,
    required this.answer,
    required this.responseStatus,
    required this.citations,
  });

  factory EvaluationDetails.fromJson(Map<String, dynamic> json) {
    var rawChunks = json['retrieved_chunks'] as List<dynamic>? ?? [];
    var rawCitations = json['citations'] as List<dynamic>? ?? [];

    return EvaluationDetails(
      enabled: json['enabled'] as bool? ?? true,
      query: json['query'] as String? ?? '',
      collectionName: json['collection_name'] as String? ?? '',
      chunkingStrategy: json['chunking_strategy'] as String? ?? 'context-aware',
      sdkVersion: json['sdk_version'] as String?,
      topK: json['top_k'] as int? ?? 5,
      metadataFilter: json['metadata_filter'] as Map<String, dynamic>?,
      retrievedChunks: rawChunks
          .map((c) => EvaluationChunk.fromJson(c as Map<String, dynamic>))
          .toList(),
      context: json['context'] as String? ?? '',
      llmPrompt: json['llm_prompt'] as String? ?? '',
      llmResponse: json['llm_response'] as String? ?? '',
      answer: json['answer'] as String? ?? '',
      responseStatus: json['response_status'] as String? ?? 'answered',
      citations: rawCitations
          .map((c) => CitationDetail.fromJson(c as Map<String, dynamic>))
          .toList(),
    );
  }
}

class QueryResponse {
  final String answer;
  final String collectionName;
  final String question;
  final List<SourceChunk> sources;
  final int chunksUsed;
  final EvaluationDetails? evaluation;

  QueryResponse({
    required this.answer,
    required this.collectionName,
    required this.question,
    required this.sources,
    required this.chunksUsed,
    this.evaluation,
  });

  factory QueryResponse.fromJson(Map<String, dynamic> json) {
    var rawSources = json['sources'] as List<dynamic>? ?? [];
    List<SourceChunk> parsedSources = rawSources
        .map((s) => SourceChunk.fromJson(s as Map<String, dynamic>))
        .toList();

    EvaluationDetails? eval;
    if (json['evaluation'] != null) {
      eval = EvaluationDetails.fromJson(
        json['evaluation'] as Map<String, dynamic>,
      );
    }

    return QueryResponse(
      answer: json['answer'] as String? ?? '',
      collectionName: json['collection_name'] as String? ?? '',
      question: json['question'] as String? ?? '',
      sources: parsedSources,
      chunksUsed: json['chunks_used'] as int? ?? 0,
      evaluation: eval,
    );
  }
}

class UploadResponse {
  final String status;
  final String collectionName;
  final String filename;
  final int chunksStored;
  final String chunkingMethod;
  final int chunkSize;
  final int chunkOverlap;

  UploadResponse({
    required this.status,
    required this.collectionName,
    required this.filename,
    required this.chunksStored,
    required this.chunkingMethod,
    required this.chunkSize,
    required this.chunkOverlap,
  });

  factory UploadResponse.fromJson(Map<String, dynamic> json) {
    return UploadResponse(
      status: json['status'] as String? ?? 'ok',
      collectionName: json['collection_name'] as String? ?? '',
      filename: json['filename'] as String? ?? '',
      chunksStored: json['chunks_stored'] as int? ?? 0,
      chunkingMethod: json['chunking_method'] as String? ?? 'context-aware',
      chunkSize: json['chunk_size'] as int? ?? 0,
      chunkOverlap: json['chunk_overlap'] as int? ?? 0,
    );
  }
}

/// One graded query's MRR outcome: where the first relevant chunk landed.
class MrrQueryEvaluation {
  final String id;
  final String question;
  final String split;
  final List<String> expectedChunkIds;
  final List<String> retrievedChunkIds;
  final int? firstRelevantRank;
  final double reciprocalRank;

  MrrQueryEvaluation({
    required this.id,
    required this.question,
    required this.split,
    required this.expectedChunkIds,
    required this.retrievedChunkIds,
    this.firstRelevantRank,
    required this.reciprocalRank,
  });

  bool get isHit => firstRelevantRank != null;

  factory MrrQueryEvaluation.fromJson(Map<String, dynamic> json) {
    return MrrQueryEvaluation(
      id: json['id'] as String? ?? '',
      question: json['question'] as String? ?? '',
      split: json['split'] as String? ?? 'test',
      expectedChunkIds:
          (json['expected_chunk_ids'] as List<dynamic>? ?? [])
              .map((e) => e.toString())
              .toList(),
      retrievedChunkIds:
          (json['retrieved_chunk_ids'] as List<dynamic>? ?? [])
              .map((e) => e.toString())
              .toList(),
      firstRelevantRank: json['first_relevant_rank'] as int?,
      reciprocalRank: (json['reciprocal_rank'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

/// MRR restricted to a single split (dev / test).
class MrrSplitScore {
  final String split;
  final int queryCount;
  final double mrr;

  MrrSplitScore({
    required this.split,
    required this.queryCount,
    required this.mrr,
  });

  factory MrrSplitScore.fromJson(Map<String, dynamic> json) {
    return MrrSplitScore(
      split: json['split'] as String? ?? '',
      queryCount: json['query_count'] as int? ?? 0,
      mrr: (json['mrr'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

/// Full response from `GET /eval/mrr`.
class MrrReport {
  final String collectionName;
  final int topK;
  final String? split;
  final int queryCount;
  final double mrr;
  final List<MrrSplitScore> splitScores;
  final List<MrrQueryEvaluation> evaluations;
  final List<String> warnings;

  MrrReport({
    required this.collectionName,
    required this.topK,
    this.split,
    required this.queryCount,
    required this.mrr,
    required this.splitScores,
    required this.evaluations,
    this.warnings = const [],
  });

  MrrSplitScore? scoreFor(String splitName) {
    for (final score in splitScores) {
      if (score.split == splitName) return score;
    }
    return null;
  }

  factory MrrReport.fromJson(Map<String, dynamic> json) {
    return MrrReport(
      collectionName: json['collection_name'] as String? ?? '',
      topK: json['top_k'] as int? ?? 5,
      split: json['split'] as String?,
      queryCount: json['query_count'] as int? ?? 0,
      mrr: (json['mrr'] as num?)?.toDouble() ?? 0.0,
      splitScores: (json['split_scores'] as List<dynamic>? ?? [])
          .map((s) => MrrSplitScore.fromJson(s as Map<String, dynamic>))
          .toList(),
      evaluations: (json['evaluations'] as List<dynamic>? ?? [])
          .map((e) => MrrQueryEvaluation.fromJson(e as Map<String, dynamic>))
          .toList(),
      warnings: (json['warnings'] as List<dynamic>? ?? [])
          .map((w) => w.toString())
          .toList(),
    );
  }
}

class ChatMessage {
  final String id;
  final String sender; // 'user' or 'ai'
  final String text;
  final DateTime timestamp;
  final List<SourceChunk>? sources;
  final EvaluationDetails? evaluation;
  final bool isLoading;

  ChatMessage({
    required this.id,
    required this.sender,
    required this.text,
    required this.timestamp,
    this.sources,
    this.evaluation,
    this.isLoading = false,
  });
}
