import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:leafcare_mobile/main.dart';

const cameraChannel = MethodChannel('plugins.flutter.io/camera');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  tearDown(() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(cameraChannel, null);
  });

  testWidgets('shows manual capture controls', (WidgetTester tester) async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(cameraChannel, (call) async {
      if (call.method == 'availableCameras') {
        return <Map<String, Object>>[];
      }
      return null;
    });

    await tester.pumpWidget(const LeafCareApp());
    await tester.pump();
    await tester.pump();

    expect(find.text('Banana leaf screening'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('Capture and analyze'),
      300,
      scrollable: find.byType(Scrollable),
    );
    expect(find.text('Capture and analyze'), findsOneWidget);
    expect(find.textContaining('every 2 seconds'), findsNothing);
  });
}
