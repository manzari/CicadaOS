import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/providers.dart';

/// Shows the raw 32-byte public key for firmware provisioning. The firmware
/// holds ONE pubkey, so exactly one signing phone can push to a given ESP;
/// multi-phone support would need a firmware pubkey list (out of scope).
class KeyScreen extends ConsumerWidget {
  const KeyScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pubkeyAsync = ref.watch(publicKeyHexProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Signing key')),
      body: pubkeyAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Error: $e')),
        data: (hex) => ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text('Public key (32 bytes, hex)', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: SelectableText(hex, style: const TextStyle(fontFamily: 'monospace')),
              ),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                FilledButton.icon(
                  onPressed: () {
                    Clipboard.setData(ClipboardData(text: hex));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('Public key copied')),
                    );
                  },
                  icon: const Icon(Icons.copy),
                  label: const Text('Copy'),
                ),
              ],
            ),
            const Divider(height: 32),
            Text('Provision an ESP', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            const _Step(1, 'Open firmware/main.py.'),
            _Step(2, 'Set PUBKEY = bytes.fromhex("$hex").'),
            const _Step(3, 'Re-deploy main.py to the board (mpremote cp).'),
            const _Step(4, 'The ESP now verifies only scripts signed by THIS phone.'),
            const SizedBox(height: 16),
            Card(
              color: Theme.of(context).colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('One phone per ESP',
                        style: TextStyle(
                            fontWeight: FontWeight.bold,
                            color: Theme.of(context).colorScheme.onErrorContainer)),
                    const SizedBox(height: 4),
                    Text(
                      'The firmware stores a single public key. Provisioning a new '
                      'phone replaces the old one — the previous phone can no longer push.',
                      style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Step extends StatelessWidget {
  final int n;
  final String text;
  const _Step(this.n, this.text);
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            CircleAvatar(radius: 12, child: Text('$n', style: const TextStyle(fontSize: 12))),
            const SizedBox(width: 12),
            Expanded(child: Text(text)),
          ],
        ),
      );
}
