import streamlit as st


def render_logout():
    st.markdown('<h2 style="margin-top:6px">Logout</h2>', unsafe_allow_html=True)
    st.markdown('Sign out from AURA and clear session data.')

    if st.button('Confirm Logout'):
        # Clear common session keys used by the app
        keys = list(st.session_state.keys())
        for k in keys:
            try:
                del st.session_state[k]
            except Exception:
                pass
        st.success('You have been logged out.')
        st.experimental_rerun()
