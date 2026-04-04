import streamlit as st
from pathlib import Path
import io
import re
from urllib.parse import urlparse
import json
import numpy as np

from PIL import Image


# ── QR decode engines ───────────────────────────────────────────────────────

def _decode_with_pyzbar(pil_img: Image.Image):
    """Primary decoder: pyzbar (requires libzbar-64.dll on Windows)."""
    try:
        from pyzbar.pyzbar import decode
        results = decode(pil_img)
        return [r.data.decode('utf-8', errors='ignore') for r in results], None
    except (ImportError, OSError):
        # ImportError  → pyzbar not installed
        # OSError      → libzbar-64.dll missing on Windows
        return None, "pyzbar"
    except Exception as e:
        return [], str(e)


def _decode_with_opencv(pil_img: Image.Image):
    """Fallback decoder: OpenCV QRCodeDetector — no system DLLs needed."""
    try:
        import cv2

        detector = cv2.QRCodeDetector()

        # Strategy 1: colour RGB
        arr = np.array(pil_img.convert('RGB'))
        bgr = arr[:, :, ::-1].copy()
        data, _, _ = detector.detectAndDecode(bgr)
        if data:
            return [data], None

        # Strategy 2: grayscale
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        data, _, _ = detector.detectAndDecode(gray)
        if data:
            return [data], None

        # Strategy 3: upscale small images (helps with low-res QR)
        h, w = gray.shape[:2]
        if max(h, w) < 600:
            scale = 600 / max(h, w)
            big = cv2.resize(gray, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_CUBIC)
            data, _, _ = detector.detectAndDecode(big)
            if data:
                return [data], None

        # Strategy 4: sharpen + threshold
        kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
        sharp = cv2.filter2D(gray, -1, kernel)
        data, _, _ = detector.detectAndDecode(sharp)
        if data:
            return [data], None

        return [], None
    except ImportError:
        return None, "opencv-python"
    except Exception as e:
        return [], str(e)


def _decode_qr(pil_img: Image.Image):
    """
    Try pyzbar first; fall back to OpenCV.
    Returns (texts: list[str], engine: str, warning: str | None)
    """
    texts, err = _decode_with_pyzbar(pil_img)

    if texts is None:
        # pyzbar missing → try opencv
        texts_cv, err_cv = _decode_with_opencv(pil_img)
        if texts_cv is None:
            return [], "none", (
                "Neither `pyzbar` nor `opencv-python` is available. "
                "Run: `pip install pyzbar opencv-python Pillow`"
            )
        if err_cv:
            return [], "opencv", f"OpenCV decoding error: {err_cv}"
        return texts_cv, "opencv", None

    if err:
        # pyzbar threw a runtime error → fallback
        texts_cv, err_cv = _decode_with_opencv(pil_img)
        if texts_cv:
            return texts_cv, "opencv", None
        return [], "pyzbar", f"Decoding error: {err}"

    return texts, "pyzbar", None


# ── Fraud Detection Engine ──────────────────────────────────────────────────

# Compiled patterns
UPI_REGEX       = re.compile(r"^[A-Za-z0-9._%+\-]{2,}@[A-Za-z]{2,}$")
UPI_SCHEME_RE   = re.compile(r"^upi://pay\?", re.IGNORECASE)
URL_REGEX       = re.compile(r"https?://|www\.", re.IGNORECASE)
IP_HOST_RE      = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
RANDOM_DOM_RE   = re.compile(r"[0-9a-f]{8,}|[a-z0-9]{20,}")     # random-looking hex or slug
GARBLE_RE       = re.compile(r"[^\x20-\x7E]")                    # non-printable / non-ASCII
BASE64_RE       = re.compile(r"^[A-Za-z0-9+/]{40,}={0,2}$")
KNOWN_BANKS     = {"sbi", "hdfc", "icici", "axis", "kotak", "ybl", "okaxis", "okhdfcbank",
                   "oksbi", "okicici", "paytm", "upi", "apl", "ibl", "barodampay",
                   "mahb", "unionbank", "cnrb", "pytm", "aubank", "idbi"}


class FraudResult:
    """Holds the full analysis result for one QR payload."""
    __slots__ = ("score", "verdict", "content_type", "flags", "safe_signals")

    def __init__(self, score, verdict, content_type, flags, safe_signals):
        self.score        = score           # float  0.0 – 1.0
        self.verdict      = verdict         # "SAFE" | "SUSPICIOUS" | "FRAUD"
        self.content_type = content_type    # human label
        self.flags        = flags           # list[str]  – fraud indicators found
        self.safe_signals = safe_signals    # list[str]  – positive signals found


def _classify_content_type(text: str) -> str:
    """Return a human-readable content type label."""
    t = text.strip()
    if UPI_SCHEME_RE.match(t):
        return "💳 UPI Payment URI"
    if '@' in t and not URL_REGEX.search(t):
        return "💳 UPI ID"
    if URL_REGEX.search(t):
        return "🌐 URL / Web Link"
    if t.startswith('{') or t.startswith('['):
        return "📦 JSON Data"
    if t.isdigit():
        return "🔢 Numeric Code"
    return "📝 Plain Text"


def _analyze_qr_content(raw: str) -> FraudResult:
    """
    Rule-based fraud detection.

    SAFE signals    → decrease risk score
    Fraud signals   → increase risk score

    Final thresholds:
        score < 0.25  →  SAFE
        0.25 ≤ score < 0.60  →  SUSPICIOUS
        score ≥ 0.60  →  FRAUD
    """
    text  = raw.strip()
    flags: list[str] = []
    safe_signals: list[str] = []
    score = 0.0

    # ── Edge case: empty ─────────────────────────────────────────────────────
    if not text:
        return FraudResult(1.0, "FRAUD", "⛔ Empty", ["Empty QR payload"], [])

    content_type = _classify_content_type(text)

    # ── SAFE: well-formed UPI payment URI ────────────────────────────────────
    if UPI_SCHEME_RE.match(text):
        # extract pa= field
        pa_match = re.search(r'pa=([^&]+)', text, re.IGNORECASE)
        pa = pa_match.group(1) if pa_match else ''
        if pa and UPI_REGEX.match(pa):
            bank = pa.split('@')[-1].lower()
            if bank in KNOWN_BANKS:
                safe_signals.append(f"Valid UPI URI with known bank handle (@{bank})")
                score -= 0.5
            else:
                safe_signals.append("Valid UPI URI format (unknown bank handle)")
                score -= 0.3
        else:
            flags.append("UPI URI but invalid pa= field")
            score += 0.3

    # ── SAFE: bare valid UPI ID (name@bank) ──────────────────────────────────
    elif '@' in text and not URL_REGEX.search(text):
        if UPI_REGEX.match(text):
            bank = text.split('@')[-1].lower()
            if bank in KNOWN_BANKS:
                safe_signals.append(f"Valid UPI ID with known bank (@{bank})")
                score -= 0.4
            else:
                safe_signals.append("Valid UPI ID format")
                score -= 0.2
        else:
            flags.append("Contains '@' but not a valid UPI ID format")
            score += 0.45

    # ── URL analysis ─────────────────────────────────────────────────────────
    elif URL_REGEX.search(text):
        try:
            u = text if text.startswith('http') else 'http://' + text
            p = urlparse(u)
            domain = (p.hostname or '').lower()
        except Exception:
            domain = ''

        if not domain:
            flags.append("Malformed or unparseable URL")
            score += 0.55
        else:
            # IP address as host → high risk
            if IP_HOST_RE.match(domain):
                flags.append(f"URL uses raw IP address ({domain}) — no legitimate domain")
                score += 0.55

            # Random-looking domain (hex strings, long random slugs)
            if RANDOM_DOM_RE.search(domain):
                flags.append("Domain contains random-looking hex/slug pattern")
                score += 0.45

            # Unusually long domain
            if len(domain) > 35:
                flags.append(f"Unusually long domain name ({len(domain)} chars)")
                score += 0.2

            # Phishing keywords mimicking banks/payment apps
            phish_kw = ["secure", "verify", "update", "login", "signin",
                        "account", "bank", "paypal", "paytm", "upi", "wallet"]
            found_kw = [kw for kw in phish_kw if kw in domain]
            if found_kw:
                flags.append(f"Domain contains phishing keyword(s): {', '.join(found_kw)}")
                score += 0.3

            # Not HTTPS
            if p.scheme == 'http':
                flags.append("URL uses HTTP (not HTTPS) — data is unencrypted")
                score += 0.15

            # TLD check — common scam TLDs
            scam_tlds = {".tk", ".ml", ".ga", ".cf", ".gq", ".xyz",
                         ".top", ".click", ".loan", ".work", ".online"}
            if any(domain.endswith(t) for t in scam_tlds):
                flags.append(f"High-risk TLD detected ({domain.rsplit('.', 1)[-1]})")
                score += 0.35

    # ── Generic text checks (applied to everything) ───────────────────────────

    # Garbled / non-printable characters
    non_print = len(GARBLE_RE.findall(text))
    if non_print > 0:
        flags.append(f"Contains {non_print} non-printable/non-ASCII character(s) — possible encoding trick")
        score += 0.5

    # Base64-encoded payload
    if BASE64_RE.match(text):
        flags.append("Payload looks like Base64-encoded data (obfuscated content)")
        score += 0.45

    # Excessive percent-encoding
    pct_count = text.count('%')
    if pct_count > 5:
        flags.append(f"High percent-encoding count ({pct_count} '%' chars) — possible obfuscation")
        score += 0.35

    # Very long payload
    if len(text) > 300:
        flags.append(f"Extremely long payload ({len(text)} chars) — abnormal for QR")
        score += 0.35
    elif len(text) > 150:
        flags.append(f"Long payload ({len(text)} chars)")
        score += 0.15

    # High ratio of non-alphanumeric characters (garbled)
    non_alnum_ratio = sum(1 for c in text if not c.isalnum()) / max(1, len(text))
    if non_alnum_ratio > 0.45 and len(text) > 20:
        flags.append(f"High non-alphanumeric ratio ({non_alnum_ratio:.0%}) — possibly garbled")
        score += 0.3

    # Clamp
    score = max(0.0, min(1.0, score))

    # Verdict
    if score < 0.25:
        verdict = "SAFE"
    elif score < 0.60:
        verdict = "SUSPICIOUS"
    else:
        verdict = "FRAUD"

    return FraudResult(score, verdict, content_type, flags, safe_signals)


# ── Main render ───────────────────────────────────────────────────────────────

def render_qr_scanner():
    st.markdown('<div class="card-title">📷 QR Scanner</div>', unsafe_allow_html=True)
    st.write('Scan or upload a QR code to verify before payment.')

    col1, col2 = st.columns([1, 1])

    img: Image.Image | None = None

    with col1:
        uploaded = st.file_uploader(
            'Upload QR image', type=['png', 'jpg', 'jpeg'],
            accept_multiple_files=False
        )
        if uploaded is not None:
            try:
                pil = Image.open(uploaded).convert('RGB')
                img = pil
            except Exception as e:
                st.error(f'Failed to open image: {e}')

        # Camera input (may not be supported in all environments)
        try:
            cam = st.camera_input('Or scan with your camera')
            if cam is not None and img is None:
                try:
                    pil2 = Image.open(io.BytesIO(cam.read())).convert('RGB')
                    img = pil2
                except Exception:
                    try:
                        cam.seek(0)
                        pil2 = Image.open(cam).convert('RGB')
                        img = pil2
                    except Exception:
                        st.warning('Could not read camera frame.')
        except Exception:
            pass  # camera_input not supported in all environments

    with col2:
        st.markdown('<div style="margin-bottom:8px">&nbsp;</div>', unsafe_allow_html=True)
        if img is not None:
            st.image(img, caption='Scanned Image', use_container_width=True)

    if img is None:
        st.info('Upload an image or use camera to begin.')
        return

    # ── Decode ───────────────────────────────────────────────────────────────
    with st.spinner('Decoding QR code…'):
        texts, engine, warning = _decode_qr(img)

    if warning:
        st.error(f'⚠️ {warning}')
        st.markdown(
            "**To fix:** open a terminal in your project folder and run:\n"
            "```\npip install pyzbar opencv-python Pillow\n```"
        )
        return

    if engine == "opencv":
        st.caption('ℹ️ Decoded via OpenCV (pyzbar unavailable)')
    elif engine == "pyzbar":
        st.caption('ℹ️ Decoded via pyzbar')

    if not texts:
        st.warning('⚠️ No QR code detected in the image. '
                   'Ensure the QR is clear, well-lit, and fully visible.')
        return

    # ── Display extracted content + fraud analysis ───────────────────────────
    st.markdown('<hr/>', unsafe_allow_html=True)
    st.success(f'✅ Successfully decoded {len(texts)} QR code(s)!')

    for i, txt in enumerate(texts):
        with st.container():

            # ── 1. Extracted Data ─────────────────────────────────────────
            st.markdown(f'### 📋 Extracted Data #{i + 1}')

            result = _analyze_qr_content(txt)

            st.markdown(f'**Content Type:** {result.content_type}')
            st.text_area(
                label='Decoded QR Text',
                value=txt,
                height=80,
                key=f'qr_text_{i}',
                help='Raw content extracted from the QR code'
            )
            st.code(txt, language=None)
            st.caption(f'Length: {len(txt)} characters')

            st.markdown('<hr style="border-color:rgba(255,255,255,0.08)"/>', unsafe_allow_html=True)

            # ── 2 & 3. Risk Score + Status ────────────────────────────────
            VERDICT_CFG = {
                "SAFE":       {"emoji": "✅", "color": "#10b981", "bg": "rgba(16,185,129,0.08)",
                               "border": "rgba(16,185,129,0.30)"},
                "SUSPICIOUS": {"emoji": "⚠️", "color": "#f59e0b", "bg": "rgba(245,158,11,0.08)",
                               "border": "rgba(245,158,11,0.30)"},
                "FRAUD":      {"emoji": "❌", "color": "#ef4444", "bg": "rgba(239,68,68,0.08)",
                               "border": "rgba(239,68,68,0.35)"},
            }
            cfg = VERDICT_CFG[result.verdict]

            col_score, col_verdict = st.columns([1, 3])

            with col_score:
                # Colour-coded risk score metric
                score_pct = int(result.score * 100)
                st.markdown(
                    f"<div style='text-align:center; padding:16px 8px; border-radius:12px; "
                    f"background:{cfg['bg']}; border:1px solid {cfg['border']};'>"
                    f"<div style='font-size:2rem; font-weight:800; color:{cfg['color']};'>"
                    f"{result.score:.2f}</div>"
                    f"<div style='font-size:0.75rem; color:#aaa; margin-top:2px;'>Risk Score</div>"
                    f"<div style='font-size:1rem; font-weight:700; margin-top:6px; color:{cfg['color']};'>"
                    f"{cfg['emoji']} {result.verdict}</div>"
                    f"</div>",
                    unsafe_allow_html=True
                )
                # Visual risk bar
                bar_w = score_pct
                bar_color = cfg['color']
                st.markdown(
                    f"<div style='margin-top:10px; background:rgba(255,255,255,0.07); "
                    f"border-radius:6px; height:8px; overflow:hidden;'>"
                    f"<div style='width:{bar_w}%; height:100%; background:{bar_color}; "
                    f"border-radius:6px; transition:width 0.4s;'></div></div>",
                    unsafe_allow_html=True
                )

            with col_verdict:
                # ── Alert banner ──────────────────────────────────────────
                if result.verdict == "FRAUD":
                    st.markdown(
                        f"<div style='padding:16px 20px; border-radius:12px; "
                        f"background:rgba(239,68,68,0.10); border:1.5px solid rgba(239,68,68,0.45);'>"
                        f"<h3 style='color:#ef4444; margin:0 0 6px;'>❌ Fraud Detected</h3>"
                        f"<p style='color:#ffd2d2; margin:0;'>"
                        f"This QR is <strong>potentially unsafe</strong>. "
                        f"Do <strong>NOT</strong> proceed with payment or follow any links.</p>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                elif result.verdict == "SUSPICIOUS":
                    st.markdown(
                        f"<div style='padding:16px 20px; border-radius:12px; "
                        f"background:rgba(245,158,11,0.08); border:1.5px solid rgba(245,158,11,0.35);'>"
                        f"<h3 style='color:#f59e0b; margin:0 0 6px;'>⚠️ Suspicious QR</h3>"
                        f"<p style='color:#fff7ed; margin:0;'>"
                        f"Proceed with caution. Verify merchant details independently before any payment.</p>"
                        f"</div>",
                        unsafe_allow_html=True
                    )
                else:  # SAFE
                    st.markdown(
                        f"<div style='padding:16px 20px; border-radius:12px; "
                        f"background:rgba(16,185,129,0.08); border:1.5px solid rgba(16,185,129,0.30);'>"
                        f"<h3 style='color:#10b981; margin:0 0 6px;'>✅ QR Verified — Safe to Proceed</h3>"
                        f"<p style='color:#bfeece; margin:0;'>"
                        f"No fraud signals detected. This QR appears legitimate.</p>"
                        f"</div>",
                        unsafe_allow_html=True
                    )

                # ── Safe signals ──────────────────────────────────────────
                if result.safe_signals:
                    st.markdown("**✔ Safe Signals:**")
                    for sig in result.safe_signals:
                        st.markdown(f"&nbsp;&nbsp;🟢 {sig}")

                # ── Fraud flags ───────────────────────────────────────────
                if result.flags:
                    st.markdown("**⚠ Risk Indicators:**")
                    for flag in result.flags:
                        icon = "🔴" if result.verdict == "FRAUD" else "🟡"
                        st.markdown(f"&nbsp;&nbsp;{icon} {flag}")

            # ── Prevention tips ───────────────────────────────────────────
            st.markdown('<hr style="border-color:rgba(255,255,255,0.06)"/>', unsafe_allow_html=True)
            with st.expander('🛡️ Prevention Tips', expanded=(result.verdict != "SAFE")):
                st.markdown(
                    '- Always verify the merchant name & UPI ID before confirming payment\n'
                    '- Never scan QR codes from unknown physical or digital sources\n'
                    '- Check that URLs use **HTTPS** and belong to a known domain\n'
                    '- Legitimate payment apps never ask you to scan to **receive** money\n'
                    '- If in doubt, type the UPI ID manually instead of using the QR'
                )

            # ── Optional backend analysis ─────────────────────────────────
            if st.checkbox('Also analyze with backend ML model (optional)', key=f'backend_{i}'):
                try:
                    import requests
                    payload = {
                        "amount": 0.0,
                        "merchant": txt if ('@' in txt or URL_REGEX.search(txt)) else None,
                        "location_risk": round(result.score, 2),
                        "device_trust": 1.0 - round(result.score, 2),
                        "txn_per_hour": 0
                    }
                    resp = requests.post(
                        st.session_state.get('backend_url', '') + '/analyze',
                        json=payload, timeout=6
                    )
                    if resp.status_code == 200:
                        st.success('Backend model response:')
                        st.json(resp.json())
                    else:
                        st.error(f'Backend returned {resp.status_code}: {resp.text[:200]}')
                except Exception as e:
                    st.error(f'Failed to call backend: {e}')

    st.markdown('<hr/>', unsafe_allow_html=True)
