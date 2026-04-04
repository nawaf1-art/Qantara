# Trust Certificate On Windows

## Purpose

The current Qantara HTTPS fallback uses a self-signed certificate.

For browser microphone access on another Windows device, the certificate must be trusted by that device. If the certificate is not trusted, the page may load with warnings, and microphone access may still be blocked.

## Files

The generated certificate currently lives at:

- `ops/certs/qantara-cert.pem`

The private key stays on the server and should not be copied to client devices.

## What The Client Device Needs

The Windows device only needs the certificate file, not the private key.

You can convert the PEM certificate to CRT if desired, but Windows can also import PEM in some flows. If needed, rename or convert it to a `.crt` file first.

## Trust Flow

On the Windows client:

1. Copy the certificate file from the Qantara machine.
2. Open the certificate file.
3. Choose `Install Certificate`.
4. Select `Local Machine` if allowed, otherwise `Current User`.
5. Choose `Place all certificates in the following store`.
6. Select `Trusted Root Certification Authorities`.
7. Complete the import.
8. Restart the browser.

## Verify

After import, open:

```text
https://192.168.68.59:9443/spike
```

Expected result:

- browser shows the page without a certificate error
- the client uses `wss://` automatically
- microphone permission can be requested normally

## Security Note

Trust this certificate only on devices that should access your internal Qantara spike. This is a development convenience, not a production certificate strategy.
