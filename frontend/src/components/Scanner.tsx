import { useEffect, useRef, useState } from "react";
import { Modal } from "./ui";

/** Camera barcode scanner (UPC/EAN and common 1D codes). Needs HTTPS, as all browser camera access does. */
export function Scanner({ onDetected, onClose }: { onDetected: (code: string) => void; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [manual, setManual] = useState("");
  const detected = useRef(onDetected);
  detected.current = onDetected;

  useEffect(() => {
    let stop: (() => void) | null = null;
    let cancelled = false;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError("The camera only works when the app is opened over HTTPS. Type the barcode below instead.");
      return;
    }
    (async () => {
      try {
        const [{ BrowserMultiFormatReader }, { BarcodeFormat, DecodeHintType }] = await Promise.all([
          import("@zxing/browser"),
          import("@zxing/library"),
        ]);
        const hints = new Map();
        hints.set(DecodeHintType.POSSIBLE_FORMATS, [
          BarcodeFormat.UPC_A, BarcodeFormat.UPC_E, BarcodeFormat.EAN_13, BarcodeFormat.EAN_8,
          BarcodeFormat.CODE_128, BarcodeFormat.CODE_39,
        ]);
        const reader = new BrowserMultiFormatReader(hints, { delayBetweenScanAttempts: 120 });
        if (cancelled || !videoRef.current) return;
        const controls = await reader.decodeFromConstraints(
          { video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } } },
          videoRef.current,
          (result, _err, ctrl) => {
            if (result && !cancelled) {
              cancelled = true;
              ctrl.stop();
              navigator.vibrate?.(60);
              detected.current(result.getText());
            }
          }
        );
        stop = () => controls.stop();
        if (cancelled) stop();
      } catch (e) {
        const name = (e as { name?: string })?.name;
        setError(
          name === "NotAllowedError"
            ? "Camera permission was denied. Allow camera access for this site in your browser settings, or type the barcode below."
            : name === "NotFoundError"
              ? "No camera found on this device. Type the barcode below."
              : "Couldn't start the camera. Type the barcode below."
        );
      }
    })();
    return () => {
      cancelled = true;
      stop?.();
    };
  }, []);

  return (
    <Modal title="Scan barcode" onClose={onClose}>
      {!error && (
        <div className="scanner-frame">
          <video ref={videoRef} className="scanner-video" muted playsInline />
        </div>
      )}
      {error ? <p className="notice warn">{error}</p> : <p className="hint">Hold the barcode inside the frame. It scans automatically.</p>}
      <form
        className="input-row"
        onSubmit={(e) => {
          e.preventDefault();
          if (manual.trim()) onDetected(manual.trim());
        }}
      >
        <label className="visually-hidden" htmlFor="manual-code">
          Barcode
        </label>
        <input id="manual-code" className="input" inputMode="numeric" placeholder="Or type the barcode" value={manual} onChange={(e) => setManual(e.target.value)} />
        <button className="btn primary" type="submit">
          Use
        </button>
      </form>
    </Modal>
  );
}
