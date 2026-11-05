# Acceso: Ejecutivo (solo lectura) o Admin (contraseña DASHBOARD_PASSWORD).
import os
import time
import hmac
import hashlib
import streamlit as st

TIMEOUT = 3600


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def modo() -> str:
    """'admin', 'ejecutivo' o '' (sin sesión)."""
    if st.session_state.get("admin_ok"):
        if time.time() - st.session_state.get("auth_time", 0) > TIMEOUT:
            st.session_state["admin_ok"] = False
            return ""
        return "admin"
    if st.session_state.get("ejecutivo_ok"):
        return "ejecutivo"
    return ""


def es_admin() -> bool:
    return modo() == "admin"


def cerrar_sesion():
    for k in ("admin_ok", "ejecutivo_ok", "auth_time"):
        st.session_state.pop(k, None)


def pantalla_login():
    st.markdown("<h1 style='text-align:center;margin-top:2rem'>⚡ MEGAZORD</h1>"
                "<p style='text-align:center;opacity:.7'>War Room</p>", unsafe_allow_html=True)
    _, centro, _ = st.columns([1, 2, 1])
    with centro:
        if st.button("👁️ Entrar como Ejecutivo (solo lectura)", width="stretch"):
            st.session_state["ejecutivo_ok"] = True
            st.rerun()
        st.divider()
        with st.form("login_admin", clear_on_submit=True):
            pwd = st.text_input("Contraseña de administrador", type="password")
            ok = st.form_submit_button("🔐 Entrar como Admin", width="stretch")
        if ok:
            # Misma contraseña que el dashboard actual (variable DASHBOARD_PASSWORD; por compatibilidad, "123" si no existe)
            esperado = _hash(os.getenv("DASHBOARD_PASSWORD", "123"))
            if hmac.compare_digest(_hash(pwd), esperado):
                st.session_state["admin_ok"] = True
                st.session_state["auth_time"] = time.time()
                st.rerun()
            else:
                st.error("Contraseña incorrecta")
