import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:image_picker/image_picker.dart';

const apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'https://kharo-can-leafcare-api.onrender.com',
);
const enableFeedbackUpload = bool.fromEnvironment(
  'ENABLE_FEEDBACK_UPLOAD',
  defaultValue: false,
);

void main() {
  runApp(const LeafCareApp());
}

class LeafCareApp extends StatelessWidget {
  const LeafCareApp({super.key});

  @override
  Widget build(BuildContext context) {
    const leafGreen = Color(0xFF287A50);
    return MaterialApp(
      title: 'LeafCare',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: leafGreen,
          surface: const Color(0xFFF6F9F5),
        ),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFFF6F9F5),
      ),
      home: const CapturePage(),
    );
  }
}

class AnnotationEditorPage extends StatefulWidget {
  const AnnotationEditorPage({
    required this.imageBytes,
    required this.imageWidth,
    required this.imageHeight,
    required this.initialBoxes,
    super.key,
  });

  final Uint8List imageBytes;
  final int imageWidth;
  final int imageHeight;
  final List<Map<String, double>> initialBoxes;

  @override
  State<AnnotationEditorPage> createState() => _AnnotationEditorPageState();
}

class _AnnotationEditorPageState extends State<AnnotationEditorPage> {
  late final List<Map<String, double>> _boxes =
      widget.initialBoxes.map((box) => Map<String, double>.from(box)).toList();
  Offset? _dragStart;
  Offset? _dragEnd;

  Offset _normalizedPosition(Offset position, Size size) {
    return Offset(
      (position.dx / size.width).clamp(0.0, 1.0).toDouble(),
      (position.dy / size.height).clamp(0.0, 1.0).toDouble(),
    );
  }

  void _finishBox() {
    final start = _dragStart;
    final end = _dragEnd;
    if (start == null || end == null) return;
    final left = start.dx < end.dx ? start.dx : end.dx;
    final top = start.dy < end.dy ? start.dy : end.dy;
    final width = (start.dx - end.dx).abs();
    final height = (start.dy - end.dy).abs();
    if (width >= 0.006 && height >= 0.006) {
      setState(() {
        _boxes.add({
          'x_center': left + width / 2,
          'y_center': top + height / 2,
          'width': width,
          'height': height,
        });
      });
    }
    setState(() {
      _dragStart = null;
      _dragEnd = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final aspectRatio = widget.imageWidth / widget.imageHeight;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Outline Sigatoka lesions'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, _boxes),
            child: const Text('Save'),
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 8, 16, 12),
              child: Text(
                'Drag on the image to draw a box around each Sigatoka lesion. '
                'Tap a box below to remove it. Only reviewed boxes are saved.',
              ),
            ),
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) {
                  final maxWidth = constraints.maxWidth;
                  final maxHeight = constraints.maxHeight;
                  final fittedWidth = maxWidth < maxHeight * aspectRatio
                      ? maxWidth
                      : maxHeight * aspectRatio;
                  final fittedHeight = fittedWidth / aspectRatio;
                  final imageSize = Size(fittedWidth, fittedHeight);
                  return Center(
                    child: SizedBox.fromSize(
                      size: imageSize,
                      child: GestureDetector(
                        behavior: HitTestBehavior.opaque,
                        onPanStart: (details) {
                          final point = _normalizedPosition(
                            details.localPosition,
                            imageSize,
                          );
                          setState(() {
                            _dragStart = point;
                            _dragEnd = point;
                          });
                        },
                        onPanUpdate: (details) {
                          setState(() {
                            _dragEnd = _normalizedPosition(
                              details.localPosition,
                              imageSize,
                            );
                          });
                        },
                        onPanEnd: (_) => _finishBox(),
                        child: Stack(
                          fit: StackFit.expand,
                          children: [
                            Image.memory(widget.imageBytes, fit: BoxFit.fill),
                            CustomPaint(
                              painter: _AnnotationPainter(
                                boxes: _boxes,
                                activeStart: _dragStart,
                                activeEnd: _dragEnd,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),
            Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                children: [
                  Expanded(child: Text('Sigatoka boxes: ${_boxes.length}')),
                  TextButton(
                    onPressed:
                        _boxes.isEmpty ? null : () => setState(_boxes.clear),
                    child: const Text('Clear all'),
                  ),
                ],
              ),
            ),
            if (_boxes.isNotEmpty)
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 116),
                child: SingleChildScrollView(
                  child: Wrap(
                    spacing: 6,
                    runSpacing: 4,
                    children: [
                      for (var index = 0; index < _boxes.length; index++)
                        InputChip(
                          label: Text('Box ${index + 1}'),
                          onDeleted: () =>
                              setState(() => _boxes.removeAt(index)),
                        ),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }
}

class _AnnotationPainter extends CustomPainter {
  const _AnnotationPainter({
    required this.boxes,
    required this.activeStart,
    required this.activeEnd,
  });

  final List<Map<String, double>> boxes;
  final Offset? activeStart;
  final Offset? activeEnd;

  @override
  void paint(Canvas canvas, Size size) {
    final existingPaint = Paint()
      ..color = Colors.redAccent
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3;
    for (final box in boxes) {
      canvas.drawRect(
        Rect.fromCenter(
          center: Offset(
            box['x_center']! * size.width,
            box['y_center']! * size.height,
          ),
          width: box['width']! * size.width,
          height: box['height']! * size.height,
        ),
        existingPaint,
      );
    }
    if (activeStart != null && activeEnd != null) {
      final drawingPaint = Paint()
        ..color = Colors.lightGreenAccent
        ..style = PaintingStyle.stroke
        ..strokeWidth = 3;
      canvas.drawRect(
        Rect.fromPoints(
          Offset(activeStart!.dx * size.width, activeStart!.dy * size.height),
          Offset(activeEnd!.dx * size.width, activeEnd!.dy * size.height),
        ),
        drawingPaint,
      );
    }
  }

  @override
  bool shouldRepaint(_AnnotationPainter oldDelegate) =>
      oldDelegate.boxes != boxes ||
      oldDelegate.activeStart != activeStart ||
      oldDelegate.activeEnd != activeEnd;
}

class CapturePage extends StatefulWidget {
  const CapturePage({super.key});

  @override
  State<CapturePage> createState() => _CapturePageState();
}

class _CapturePageState extends State<CapturePage> with WidgetsBindingObserver {
  CameraController? _cameraController;
  final ImagePicker _imagePicker = ImagePicker();
  bool _isAnalyzing = false;
  bool _isSavingFeedback = false;
  bool _feedbackSaved = false;
  String _status = 'Starting camera...';
  int _detectionCount = 0;
  int _savedSampleCount = 0;
  String _imageSource = 'camera';
  List<Map<String, dynamic>> _classConfidences = [];
  List<Map<String, dynamic>> _detections = [];
  Uint8List? _currentImageBytes;
  Uint8List? _annotatedImage;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(_initializeCamera());
    if (enableFeedbackUpload) {
      unawaited(_loadFeedbackStats());
    }
  }

  Future<void> _initializeCamera() async {
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) {
        throw CameraException('NoCamera', 'No camera is available.');
      }

      final selectedCamera = cameras.firstWhere(
        (camera) => camera.lensDirection == CameraLensDirection.back,
        orElse: () => cameras.first,
      );
      final controller = CameraController(
        selectedCamera,
        ResolutionPreset.medium,
        enableAudio: false,
      );
      await controller.initialize();
      if (!mounted) {
        await controller.dispose();
        return;
      }
      setState(() {
        _cameraController = controller;
        _status = 'Camera ready. Capture a leaf image to analyze it.';
      });
    } on CameraException catch (error) {
      if (mounted) {
        setState(() {
          _status = 'Camera error: ${error.description ?? error.code}';
        });
      }
    }
  }

  Future<void> _captureAndAnalyze() async {
    final controller = _cameraController;
    if (_isAnalyzing || controller == null || !controller.value.isInitialized) {
      return;
    }

    try {
      final photo = await controller.takePicture();
      try {
        await _analyzeImage(await photo.readAsBytes(), source: 'camera');
      } finally {
        await File(photo.path).delete();
      }
    } on FileSystemException catch (error) {
      _setStatus('Captured image file error: ${error.message}');
    } on CameraException catch (error) {
      _setStatus('Camera error: ${error.description ?? error.code}');
    }
  }

  Future<void> _chooseImage() async {
    if (_isAnalyzing || _isSavingFeedback) return;
    try {
      final photo = await _imagePicker.pickImage(
        source: ImageSource.gallery,
        imageQuality: 95,
      );
      if (photo == null) return;
      await _analyzeImage(await photo.readAsBytes(), source: 'gallery');
    } on PlatformException catch (error) {
      _setStatus(
          'Could not open photo gallery: ${error.message ?? error.code}');
    } on FileSystemException catch (error) {
      _setStatus('Selected image could not be read: ${error.message}');
    }
  }

  Future<void> _analyzeImage(
    Uint8List imageBytes, {
    required String source,
  }) async {
    setState(() {
      _isAnalyzing = true;
      _feedbackSaved = false;
      _currentImageBytes = imageBytes;
      _imageSource = source;
      _status = 'Sending image for local analysis...';
      _annotatedImage = null;
      _detections = [];
      _classConfidences = [];
      _detectionCount = 0;
    });
    try {
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$apiBaseUrl/api/analyze'),
      )..files.add(
          http.MultipartFile.fromBytes(
            'image',
            imageBytes,
            filename: 'leafcare-${DateTime.now().millisecondsSinceEpoch}.jpg',
          ),
        );
      final response = await request
          .send()
          .then(http.Response.fromStream)
          .timeout(const Duration(seconds: 120));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpException(_responseError(response.body));
      }

      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException('The API returned an invalid response.');
      }
      final annotatedImageData = decoded['annotated_image_base64'];
      final scoreData = decoded['class_confidences'];
      final detectionData = decoded['detections'];
      final countData = decoded['detection_count'];
      final summaryData = decoded['summary'];
      if (annotatedImageData is! String ||
          scoreData is! Map<String, dynamic> ||
          detectionData is! List<dynamic> ||
          countData is! int ||
          summaryData is! String) {
        throw const FormatException(
          'The API response is missing analysis data.',
        );
      }
      final classConfidences = <Map<String, dynamic>>[];
      for (final entry in scoreData.entries) {
        if (entry.value is! num) {
          throw const FormatException(
            'The API returned an invalid detection confidence.',
          );
        }
        final confidence = entry.value as num;
        if (!confidence.isFinite || confidence < 0 || confidence > 1) {
          throw const FormatException(
            'The API returned an invalid detection confidence.',
          );
        }
        classConfidences.add({
          'class': entry.key,
          'confidence': confidence.toDouble(),
        });
      }
      final detections = <Map<String, dynamic>>[];
      for (final item in detectionData) {
        if (item is! Map<String, dynamic> ||
            item['class'] is! String ||
            item['confidence'] is! num) {
          throw const FormatException('The API returned an invalid detection.');
        }
        final detection = <String, dynamic>{'class': item['class']};
        for (final key in [
          'confidence',
          'x_center',
          'y_center',
          'width',
          'height',
        ]) {
          final value = item[key];
          if (value is! num ||
              !value.isFinite ||
              value < 0 ||
              value > 1 ||
              ((key == 'width' || key == 'height') && value == 0)) {
            throw const FormatException(
              'The API returned an invalid detection box.',
            );
          }
          detection[key] = value.toDouble();
        }
        detections.add(detection);
      }
      final annotatedImage = base64Decode(annotatedImageData);

      if (!mounted) return;
      setState(() {
        _classConfidences = classConfidences;
        _detections = detections;
        _detectionCount = countData;
        _annotatedImage = annotatedImage;
        _status = summaryData;
      });
    } on SocketException {
      _setStatus(
        'Cannot reach the inference API. Check its address and network.',
      );
    } on TimeoutException {
      _setStatus('Analysis timed out. Check the API and network connection.');
    } on HttpException catch (error) {
      _setStatus(error.message);
    } on FormatException catch (error) {
      _setStatus('Invalid API response: ${error.message}');
    } on http.ClientException catch (error) {
      _setStatus('Request failed: ${error.message}');
    } finally {
      if (mounted) {
        setState(() {
          _isAnalyzing = false;
        });
      }
    }
  }

  List<Map<String, double>> _sigatokaBoxes() {
    return _detections
        .where(
          (detection) =>
              (detection['class'] as String).toLowerCase() == 'sigatoka',
        )
        .map(
          (detection) => {
            'x_center': detection['x_center'] as double,
            'y_center': detection['y_center'] as double,
            'width': detection['width'] as double,
            'height': detection['height'] as double,
          },
        )
        .toList();
  }

  Future<void> _reviewAsCorrect() async {
    await _saveReview('correct', _sigatokaBoxes());
  }

  Future<void> _reviewAsNoLesions() async {
    await _saveReview('no_lesions', const []);
  }

  Future<void> _editAnnotations() async {
    final imageBytes = _currentImageBytes;
    if (imageBytes == null || _isSavingFeedback) return;
    final decodedImage = await decodeImageFromList(imageBytes);
    if (!mounted) return;
    final annotations =
        await Navigator.of(context).push<List<Map<String, double>>>(
      MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => AnnotationEditorPage(
          imageBytes: imageBytes,
          imageWidth: decodedImage.width,
          imageHeight: decodedImage.height,
          initialBoxes: _sigatokaBoxes(),
        ),
      ),
    );
    if (annotations != null) {
      await _saveReview('edited', annotations);
    }
  }

  Future<void> _saveReview(
    String decision,
    List<Map<String, double>> annotations,
  ) async {
    final imageBytes = _currentImageBytes;
    if (imageBytes == null || _feedbackSaved || _isSavingFeedback) return;
    setState(() {
      _isSavingFeedback = true;
      _status = 'Saving reviewed image to this PC...';
    });
    try {
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('$apiBaseUrl/api/feedback'),
      )
        ..fields['source'] = _imageSource
        ..fields['decision'] = decision
        ..fields['detections_json'] = jsonEncode(_detections)
        ..fields['annotations_json'] = jsonEncode(annotations)
        ..files.add(
          http.MultipartFile.fromBytes(
            'image',
            imageBytes,
            filename: 'leafcare-reviewed.jpg',
          ),
        );
      final response = await request
          .send()
          .then(http.Response.fromStream)
          .timeout(const Duration(seconds: 120));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpException(_responseError(response.body));
      }
      final payload = jsonDecode(response.body);
      if (payload is! Map<String, dynamic> || payload['id'] is! String) {
        throw const FormatException('The API returned an invalid save result.');
      }
      if (!mounted) return;
      setState(() {
        _feedbackSaved = true;
        _savedSampleCount++;
        _status = 'Review saved to the PC training database.';
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Reviewed sample saved on the PC.')),
      );
    } on SocketException {
      _setStatus('Could not save feedback: the PC API is unreachable.');
    } on TimeoutException {
      _setStatus('Saving feedback timed out. Check the PC API.');
    } on HttpException catch (error) {
      _setStatus('Could not save feedback: ${error.message}');
    } on FormatException catch (error) {
      _setStatus('Could not save feedback: ${error.message}');
    } on http.ClientException catch (error) {
      _setStatus('Could not save feedback: ${error.message}');
    } finally {
      if (mounted) {
        setState(() {
          _isSavingFeedback = false;
        });
      }
    }
  }

  Future<void> _loadFeedbackStats() async {
    try {
      final response = await http
          .get(Uri.parse('$apiBaseUrl/api/feedback/stats'))
          .timeout(const Duration(seconds: 15));
      if (response.statusCode != 200) {
        throw HttpException(_responseError(response.body));
      }
      final payload = jsonDecode(response.body);
      if (payload is! Map<String, dynamic> || payload['total'] is! int) {
        throw const FormatException(
            'The API returned invalid feedback totals.');
      }
      if (mounted) setState(() => _savedSampleCount = payload['total'] as int);
    } on SocketException {
      _setStatus('Cannot reach the inference API to load saved sample count.');
    } on TimeoutException {
      _setStatus('Loading saved sample count timed out.');
    } on HttpException catch (error) {
      _setStatus('Could not load saved sample count: ${error.message}');
    } on FormatException catch (error) {
      _setStatus('Could not load saved sample count: ${error.message}');
    } on http.ClientException catch (error) {
      _setStatus('Could not load saved sample count: ${error.message}');
    }
  }

  Future<void> _copyDatasetExportUrl() async {
    final url = '$apiBaseUrl/api/dataset/export';
    await Clipboard.setData(ClipboardData(text: url));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text(
          'Colab dataset URL copied. Open it on the PC to download the ZIP.',
        ),
      ),
    );
  }

  String _responseError(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic> && decoded['detail'] is String) {
        return decoded['detail'] as String;
      }
    } on FormatException {
      return 'The inference API returned an error.';
    }
    return 'The inference API returned an error.';
  }

  void _setStatus(String message) {
    if (mounted) {
      setState(() {
        _status = message;
      });
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.inactive ||
        state == AppLifecycleState.paused) {
      final controller = _cameraController;
      if (controller == null) return;
      _cameraController = null;
      unawaited(controller.dispose());
    } else if (state == AppLifecycleState.resumed &&
        _cameraController == null) {
      unawaited(_initializeCamera());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    final controller = _cameraController;
    if (controller != null) {
      unawaited(controller.dispose());
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = _cameraController;
    return Scaffold(
      appBar: AppBar(
        title: const Text('LeafCare'),
        actions: enableFeedbackUpload
            ? [
                IconButton(
                  onPressed: _copyDatasetExportUrl,
                  tooltip: 'Copy Colab dataset export URL',
                  icon: const Icon(Icons.archive_outlined),
                ),
              ]
            : const [],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            'Banana leaf screening',
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
          ),
          const SizedBox(height: 6),
          Text(
            'Keep a leaf in view, then capture a photo when you are ready.',
            style: Theme.of(context).textTheme.bodyMedium,
          ),
          const SizedBox(height: 16),
          ClipRRect(
            borderRadius: BorderRadius.circular(20),
            child: AspectRatio(
              aspectRatio: 4 / 3,
              child: controller != null && controller.value.isInitialized
                  ? CameraPreview(controller)
                  : const ColoredBox(
                      color: Color(0xFFE6ECE5),
                      child: Center(child: CircularProgressIndicator()),
                    ),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: controller == null ||
                    !controller.value.isInitialized ||
                    _isAnalyzing
                ? null
                : _captureAndAnalyze,
            icon: _isAnalyzing
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.camera_alt),
            label: Text(_isAnalyzing ? 'Analyzing...' : 'Capture and analyze'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _isAnalyzing || _isSavingFeedback ? null : _chooseImage,
            icon: const Icon(Icons.photo_library_outlined),
            label: const Text('Upload photo'),
          ),
          const SizedBox(height: 16),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Latest analysis',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  Text(_status),
                  const SizedBox(height: 8),
                  Text('Possible spots: $_detectionCount'),
                  if (_classConfidences.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Text(
                      'Detected classes',
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    for (final score in _classConfidences)
                      Padding(
                        padding: const EdgeInsets.only(top: 6),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(score['class'] as String),
                            ),
                            Text(
                              '${((score['confidence'] as double) * 100).toStringAsFixed(1)}%',
                            ),
                          ],
                        ),
                      ),
                  ],
                ],
              ),
            ),
          ),
          if (_annotatedImage != null) ...[
            const SizedBox(height: 12),
            Text(
              'Latest analyzed frame',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            ClipRRect(
              borderRadius: BorderRadius.circular(16),
              child: Image.memory(_annotatedImage!, fit: BoxFit.contain),
            ),
          ],
          if (enableFeedbackUpload &&
              _currentImageBytes != null &&
              _annotatedImage != null &&
              !_feedbackSaved) ...[
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Help improve LeafCare',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      'Choose whether the result is right. Reviewed images and '
                      'boxes are saved on this PC for future training.',
                    ),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        FilledButton.icon(
                          onPressed:
                              _isSavingFeedback ? null : _reviewAsCorrect,
                          icon: const Icon(Icons.thumb_up_outlined),
                          label: const Text('Correct'),
                        ),
                        OutlinedButton.icon(
                          onPressed:
                              _isSavingFeedback ? null : _editAnnotations,
                          icon: const Icon(Icons.edit_location_alt_outlined),
                          label: const Text('Edit boxes'),
                        ),
                        OutlinedButton.icon(
                          onPressed:
                              _isSavingFeedback ? null : _reviewAsNoLesions,
                          icon: const Icon(Icons.hide_source_outlined),
                          label: const Text('No Sigatoka'),
                        ),
                      ],
                    ),
                    if (_isSavingFeedback) ...[
                      const SizedBox(height: 12),
                      const LinearProgressIndicator(),
                    ],
                    const SizedBox(height: 8),
                    Text('Reviewed samples on PC: $_savedSampleCount'),
                  ],
                ),
              ),
            ),
          ],
          const SizedBox(height: 8),
          if (enableFeedbackUpload)
            TextButton.icon(
              onPressed: _copyDatasetExportUrl,
              icon: const Icon(Icons.download_outlined),
              label: const Text('Copy Colab training ZIP link'),
            ),
          const SizedBox(height: 12),
          Text(
            'Images are sent to your configured API for model analysis. '
            'Results are informational, not a substitute for expert advice.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
