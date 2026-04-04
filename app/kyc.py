import streamlit as st
from pathlib import Path
from backend.database import save_kyc_submission


def render_kyc():
    st.markdown('<h2 style="margin-top:6px">KYC Verification</h2>', unsafe_allow_html=True)
    st.markdown('Complete your identity verification to unlock all features.')

    cols = st.columns([1, 1, 1])
    with cols[0]:
        st.markdown('<div style="text-align:center"><div style="width:84px;height:84px;border-radius:42px;background:#0f1724;display:inline-flex;align-items:center;justify-content:center">⬆️</div><div style="margin-top:8px">Upload ID</div></div>', unsafe_allow_html=True)
    with cols[1]:
        st.markdown('<div style="text-align:center"><div style="width:84px;height:84px;border-radius:42px;background:#0f1724;display:inline-flex;align-items:center;justify-content:center">📸</div><div style="margin-top:8px">Face Verification</div></div>', unsafe_allow_html=True)
    with cols[2]:
        st.markdown('<div style="text-align:center"><div style="width:84px;height:84px;border-radius:42px;background:#0f1724;display:inline-flex;align-items:center;justify-content:center">✅</div><div style="margin-top:8px">Complete</div></div>', unsafe_allow_html=True)

    st.markdown("---")

    # Upload area
    st.markdown('<div style="padding:12px;border:1px dashed rgba(148,163,184,0.12);border-radius:8px;background:rgba(2,6,23,0.5)">', unsafe_allow_html=True)
    uploaded = st.file_uploader("Click to upload your ID", type=["png","jpg","jpeg","pdf"], help="Supported: Driver\'s License, Passport, National ID (PNG/JPG/PDF)", key="kyc_file_upload_widget")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div style="margin-top:18px"></div>', unsafe_allow_html=True)

    with st.form("kyc_form"):
        id_type = st.selectbox("ID Type", ["Passport", "Driver's License", "National ID", "Other"], key="kyc_id_type_select")
        id_number = st.text_input("ID Number", key="kyc_id_number_input")
        address = st.text_area("Address", height=80, key="kyc_address_area")
        submit = st.form_submit_button("Submit KYC")

        if submit:
            # Basic validation
            if not uploaded:
                st.warning("Please upload an ID document before submitting.")
            elif not id_number:
                st.warning("Please enter your ID number.")
            else:
                # Persist KYC to disk and DB
                try:
                    file_bytes = uploaded.getvalue()
                    filename = uploaded.name or 'upload'
                    username = st.session_state.get('username', 'anonymous')
                    row = save_kyc_submission(username=username, id_type=id_type, id_number=id_number, file_bytes=file_bytes, filename=filename)
                    st.success("KYC submitted. We will review and update your account shortly.")
                    st.session_state['kyc_submitted'] = True
                    st.session_state['kyc_kyc_id'] = row.id
                except Exception as e:
                    st.error(f"Failed to save KYC: {e}")

    # Optional face capture
    st.markdown('<div style="margin-top:18px;font-weight:700">Capture your face for liveness check</div>', unsafe_allow_html=True)
    try:
        cam = st.camera_input("Capture your face for liveness check")
        if cam is not None:
            st.image(cam, caption="Captured image", use_column_width=True)
            st.session_state['kyc_face'] = True
    except Exception:
        # camera_input may not work in some environments — ignore silently
        pass

